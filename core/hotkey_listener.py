"""Background global hotkey listener for WinWhispr.

Registers a system-wide hotkey via the ``keyboard`` library. On trigger it runs
the simulated text pipeline and types the result into whichever window holds
focus, then logs the session to the analytics database.
"""

import threading
import queue
import time

import keyboard
import pyperclip

from core import commands, paths, snippets
from core.active_window import active_app_name
from core.cleanup import CleanupContext, CleanupLevel, VocabEntry
from core.cleanup.orchestrator import DEFAULT_TIMEOUT_MS, run_cleanup
from core.cleanup.provider_local import LocalCleanupProvider
from core import diagnostics
from core.diagnostics import Failure, diagnose
from core.dictionary import DictionaryStore
from core.state import (
    BarState,
    Binding,
    Cancel,
    Committed,
    DictationMachine,
    DiscardCapture,
    Down,
    Failed,
    PlayPing,
    RunPipeline,
    ShowBar,
    StartCapture,
    StopCaptureAndFinalize,
    Tick,
    Up,
    WarnSessionCap,
)
from core.state.timing import TICK_MS
from core.processor import TextPipeline
from core.reformatter import Reformatter
from database import db_manager

# Default combo; overridden by config.json at startup.
DEFAULT_HOTKEY = "ctrl+shift+space"
DEFAULT_REFORMAT_HOTKEY = "ctrl+alt+r"

# Paste shortcut used for text injection. Plain Ctrl+V is accepted by virtually
# every app; Ctrl+Shift+V is not a paste shortcut in some apps (e.g. Outlook),
# which reject it with a warning beep and no paste.
PASTE_HOTKEY = "ctrl+v"

# How long to wait after Ctrl+V before restoring the previous clipboard. Slow
# apps (Outlook) read the clipboard asynchronously; restoring too early makes
# them paste the STALE previous content instead of the injected text. This runs
# on the background key thread *after* the paste, so it never delays how fast
# text appears to the user.
PASTE_SETTLE_SECONDS = 0.25

# How a session's text reaches the focused app.
#   "buffered" - accumulate the whole utterance, then paste once. Required for
#                the cleanup pass (its safety gates compare the WHOLE raw text
#                against the whole cleaned text; per-chunk ratios are noise) and
#                for discard-on-cancel.
#   "stream"   - paste each recognized chunk live, as you speak. No cleanup.
COMMIT_BUFFERED = "buffered"
COMMIT_STREAM = "stream"
DEFAULT_COMMIT_MODE = COMMIT_BUFFERED

# Hold-to-talk key. Right Ctrl is the default because it is reachable by the
# little finger, is rarely a shortcut on its own, and (unlike a chord) leaves no
# modifier held down when the paste fires.
DEFAULT_PTT_KEY = "right ctrl"
DEFAULT_CANCEL_KEY = "esc"

# Reuse the last transcript without re-dictating it.
DEFAULT_PASTE_LAST_HOTKEY = "ctrl+alt+v"
DEFAULT_COPY_LAST_HOTKEY = "ctrl+alt+c"

# How long to wait before retrying a keyboard hook that failed to install.
HOOK_RETRY_SECONDS = 5.0


class HotkeyListener:
    """Runs the global hotkey hook on a dedicated daemon thread."""

    def __init__(
        self,
        hotkey=DEFAULT_HOTKEY,
        type_delay=0.01,
        model_name="Cohere-transcribe",
        vad_threshold=0.5,
        log_transcript=False,
        device="GPU",
        min_silence_ms=300.0,
        max_segment_seconds=None,
        input_device=None,
        reformat_hotkey=DEFAULT_REFORMAT_HOTKEY,
        llm_model="LFM2.5 350M",
        llm_device="CPU",
        commit_mode=DEFAULT_COMMIT_MODE,
        cleanup_level="light",
        cleanup_provider="local",
        groq_cleanup_model=None,
        cleanup_timeout_ms=DEFAULT_TIMEOUT_MS,
        per_app_formatting=True,
        dictionary=None,
        autolearn_enabled=False,
        ptt_enabled=True,
        ptt_key=DEFAULT_PTT_KEY,
        cancel_key=DEFAULT_CANCEL_KEY,
        hands_free_double_tap=False,
        toggle_enabled=False,
        sound_on_start=True,
        paste_last_hotkey=DEFAULT_PASTE_LAST_HOTKEY,
        copy_last_hotkey=DEFAULT_COPY_LAST_HOTKEY,
        on_note=None,
        on_state=None,
        on_llm_state=None,
        on_bar=None,
        on_diagnostic=None,
        on_level=None,
    ):
        self._hotkey = hotkey or DEFAULT_HOTKEY
        self._type_delay = type_delay
        self._pipeline = TextPipeline(
            model_display_name=model_name,
            vad_threshold=vad_threshold,
            log_transcript=log_transcript,
            device=device,
            min_silence_ms=min_silence_ms,
            max_segment_seconds=max_segment_seconds,
            on_level=on_level,
            input_device=input_device or None,
        )
        self._reformat_hotkey = reformat_hotkey or DEFAULT_REFORMAT_HOTKEY
        self._reformatter = Reformatter(
            model_display_name=llm_model,
            device=llm_device,
        )
        self._commit_mode = commit_mode or DEFAULT_COMMIT_MODE
        # Cleanup shares the reformatter's warm pipeline, so it costs no extra
        # model load and the two can never generate at the same time.
        self._cleanup_level = CleanupLevel.parse(cleanup_level)
        self._cleanup_timeout_ms = int(cleanup_timeout_ms)
        self._per_app_formatting = bool(per_app_formatting)
        self._cleanup_provider = self._build_cleanup_provider(
            cleanup_provider, groq_cleanup_model
        )
        self._dictionary = dictionary if dictionary is not None else DictionaryStore(
            paths.dictionary_path()
        ).load()
        self._snippets = snippets.load(paths.snippets_path())
        # Off unless asked for: the watcher reads the contents of whatever
        # field has focus, which can be a password box or a banking form.
        self._autolearn_enabled = bool(autolearn_enabled)
        self._ptt_enabled = bool(ptt_enabled)
        # Compared against the key event's own name, so store it normalized.
        self._ptt_key = (ptt_key or DEFAULT_PTT_KEY).strip().lower()
        self._cancel_key = (cancel_key or DEFAULT_CANCEL_KEY).strip().lower()
        self._toggle_enabled = bool(toggle_enabled)
        self._sound_on_start = bool(sound_on_start)
        self._paste_last_hotkey = paste_last_hotkey
        self._copy_last_hotkey = copy_last_hotkey
        self._on_note = on_note
        self._on_state = on_state
        self._on_llm_state = on_llm_state
        self._on_bar = on_bar
        self._on_diagnostic = on_diagnostic
        self._thread = None
        self._key_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._key_thread = None
        self._dictation_thread = None
        self._llm_thread = None
        self._reformat_lock = threading.Lock()
        self._reformat_busy = False
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()

        # The state machine owns hold/tap/lock/cancel/cooldown semantics. Key
        # events and ticks arrive on _events; _machine_loop is the only thread
        # that touches the machine, so the state needs no lock.
        self._machine = DictationMachine(allow_lock=bool(hands_free_double_tap))
        self._events: queue.Queue = queue.Queue()
        self._machine_thread = None
        # Windows repeats WM_KEYDOWN while a key is held; this collapses the
        # repeats into the one press the machine should see.
        self._ptt_down = False
        self._discard = threading.Event()
        self._session = 0

    def _key_worker(self):
        while True:
            text = self._key_queue.get()
            if not text:
                continue
            try:
                # Inject the chunk via clipboard paste. We deliberately do NOT
                # restore the clipboard here: doing so per-chunk both races the
                # target app's async paste (slow apps like Outlook then paste the
                # stale previous clipboard) and serialises the key thread, making
                # dictation laggy. The original clipboard is saved once at session
                # start and restored once when dictation stops.
                pyperclip.copy(text + " ")
                keyboard.send(PASTE_HOTKEY)
                time.sleep(0.02)  # brief spacing so consecutive pastes land in order
            except Exception as exc:  # pragma: no cover - runtime guard
                print(f"[WinWhispr][hotkey] Clipboard paste failed: {exc}")
                self._report(Failure.CLIPBOARD_UNAVAILABLE)

    def _restore_clipboard(self, saved: str):
        """Restore the pre-session clipboard, once all chunks have been pasted.

        Waits for the injection queue to drain and the final paste to settle so
        we never overwrite the clipboard before the target app has read it.
        """
        deadline = time.time() + 3.0
        while not self._key_queue.empty() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(PASTE_SETTLE_SECONDS)  # let the last paste be consumed
        try:
            pyperclip.copy(saved)
        except Exception as exc:  # pragma: no cover - clipboard backend dependent
            print(f"[WinWhispr][hotkey] Clipboard restore failed: {exc}")

    def _dictation_loop(self, session: int = 0):
        # One "session" spans a full hotkey press -> press cycle. In stream mode
        # each recognized chunk is injected live (text appears as you speak); in
        # buffered mode nothing is injected until the session ends, so the whole
        # utterance can be cleaned up and pasted once. Either way the session is
        # accumulated and logged as a SINGLE entry.
        streaming = self._commit_mode == COMMIT_STREAM
        session_parts: list[str] = []
        session_start = time.time()
        # Snapshot the user's clipboard once; restored after the session ends so
        # live injection never races a per-chunk restore.
        try:
            saved_clipboard = pyperclip.paste()
        except Exception:  # pragma: no cover - clipboard backend dependent
            saved_clipboard = ""
        # Open one continuous mic stream for the whole session so audio keeps
        # buffering during ASR (no dropped packets between windows).
        self._pipeline.start_capture()
        spoke_secs = 0.0
        asr_ms = 0.0
        try:
            while not self._stop_event.is_set():
                try:
                    text, _duration = self._pipeline.process(
                        stop_event=self._stop_event,
                    )
                except Exception as exc:  # pragma: no cover - runtime guard
                    print(f"[WinWhispr][hotkey] Dictation loop error: {exc}")
                    continue
                if text:
                    if streaming:
                        self._key_queue.put(text)  # live-inject into the focused app
                    session_parts.append(text)
            # How long the user actually spoke. Measured here, before the
            # transcription work below: a session's duration is the time the
            # key was held, not the time the machine then spent thinking. The
            # two used to be conflated, which inflated every session's duration
            # and quietly halved the reported words-per-minute.
            spoke_secs = time.time() - session_start

            # Flush the final in-progress utterance (no trailing silence yet).
            # For a cloud model this is where the single request happens.
            asr_start = time.time()
            try:
                text, _duration = self._pipeline.flush()
                if text:
                    if streaming:
                        self._key_queue.put(text)
                    session_parts.append(text)
            except Exception as exc:  # pragma: no cover - runtime guard
                print(f"[WinWhispr][hotkey] Dictation flush error: {exc}")
                self._report_transcription_error(exc)
            asr_ms = (time.time() - asr_start) * 1000
        finally:
            self._pipeline.stop_capture()
            duration = spoke_secs or (time.time() - session_start)
            wait_start = time.time()
            raw_text = " ".join(p for p in session_parts if p).strip()
            final_text = raw_text
            discarded = self._discard.is_set()
            if discarded:
                # Cancelled mid-session: the audio and the transcript both go in
                # the bin, and nothing is pasted or logged.
                final_text = ""
                raw_text = ""
            elif raw_text and not streaming:
                # Buffered commit: the single injection point for the session.
                # Everything that needs the whole utterance (cleanup, gates,
                # dictionary) happens here, before the one paste.
                final_text = self._commit_text(raw_text)
                if final_text:
                    self._key_queue.put(final_text)
            # Restore last: it waits for the injection queue to drain, so it must
            # run after the buffered paste has been queued.
            self._restore_clipboard(saved_clipboard)
            if raw_text or asr_ms:
                # The whole wait, split by stage. Without this breakdown "it
                # feels slow" is unactionable: transcription and cleanup are
                # different problems with different fixes.
                waited = (time.time() - wait_start) * 1000
                print(
                    f"[WinWhispr][timing] spoke {duration:.1f}s · "
                    f"asr {asr_ms:.0f}ms · after-release {waited:.0f}ms "
                    f"({self._pipeline_label()})"
                )

        pending_key = None if discarded else (getattr(self, "_last_commit", None) or {}).get("key")
        if pending_key:
            # Sent after the clipboard settle, so the keypress lands on text
            # that is already in the target app.
            try:
                keyboard.send(pending_key)
            except Exception as exc:  # pragma: no cover - runtime guard
                print(f"[WinWhispr][hotkey] Could not send '{pending_key}': {exc}")

        if final_text and not discarded and self._autolearn_enabled:
            self._watch_for_correction(final_text)

        if not discarded:
            self._finalize_session(final_text, raw_text, duration)
            if not final_text and not pending_key:
                self._report_nothing_heard()
        self._post(Committed(session) if (final_text or pending_key) else Failed(session))

    def _commit_text(self, raw_text: str) -> str:
        """Whole-utterance processing before the buffered paste.

        Returns the text to actually paste. Never raises and never returns
        empty for non-empty input — every failure path falls back to the raw
        transcript rather than losing the user's words.
        """
        app = active_app_name()
        self._last_commit = {"app": app, "cleaned": False}
        try:
            ctx = CleanupContext(
                level=self._cleanup_level,
                app_name=app if self._per_app_formatting else None,
                vocab=self._vocab_for(raw_text),
            )
            result = run_cleanup(
                raw_text,
                ctx,
                self._cleanup_provider,
                timeout_ms=self._cleanup_timeout_ms,
            )
            self._last_commit["cleaned"] = not result.used_raw
            print(
                f"[WinWhispr][cleanup] {result.latency_ms}ms "
                f"{'raw' if result.used_raw else 'cleaned'}"
                + (f" ({result.reason})" if result.reason else "")
            )
            text = result.text or raw_text
            # Snippets and spoken commands run after cleanup, so the model can
            # neither expand a trigger itself nor rewrite a command cue away.
            text = snippets.expand(text, self._snippets)
            parsed = commands.parse(text)
            self._last_commit["key"] = parsed.key
            return parsed.text
        except Exception as exc:  # pragma: no cover - last-resort guard
            print(f"[WinWhispr][cleanup] failed, pasting raw: {exc}")
            return raw_text

    def _build_cleanup_provider(self, choice: str, groq_model: str | None):
        """Pick the cleanup backend. Unknown values fall back to local."""
        if str(choice).lower() == "groq":
            from core.cleanup.provider_groq import GroqCleanupProvider
            from core.groq_client import DEFAULT_CHAT_MODEL
            from core.secrets import has_key

            if has_key("groq_api_key"):
                return GroqCleanupProvider(groq_model or DEFAULT_CHAT_MODEL)
            # No key: quietly use what is available rather than failing every
            # cleanup and pasting raw for reasons the user cannot see.
            print("[WinWhispr][cleanup] no Groq key — using the local model")
        # Local shares the reformatter's warm pipeline, so it costs no extra
        # model load and the two can never generate at the same time.
        return LocalCleanupProvider(self._reformatter)

    def _pipeline_label(self) -> str:
        """Which engines this session used, for the timing line."""
        asr = getattr(self._pipeline, "_model_display_name", "?")
        cleanup = getattr(self._cleanup_provider, "id", "?")
        return f"asr={asr}, cleanup={cleanup}"

    def _report_nothing_heard(self) -> None:
        """Say *why* nothing came out: a dead mic and a missed word differ."""
        try:
            stats = self._pipeline.session_audio_stats()
        except Exception:  # pragma: no cover - pipeline guard
            stats = {}
        print(
            "[WinWhispr][asr] nothing recognized "
            f"(audio {stats.get('seconds', '?')}s, peak {stats.get('peak', '?')})"
        )
        if stats.get("samples", 0) == 0 or stats.get("silent"):
            self._report(Failure.NO_AUDIO_CAPTURED)
        else:
            self._report(Failure.EMPTY_TRANSCRIPT)

    def _report_transcription_error(self, exc: Exception) -> None:
        """Turn a transcription failure into copy the user can act on."""
        kind = getattr(exc, "kind", None)
        if kind:
            diag = diagnostics.for_cloud_error(kind)
            print(f"[WinWhispr][diag] {diag.headline}: {diag.detail}")
            if self._on_diagnostic is not None:
                try:
                    self._on_diagnostic(diag.headline, diag.detail)
                except Exception:  # pragma: no cover - callback guard
                    pass
            return
        self._report(Failure.ASR_UNAVAILABLE)

    def _watch_for_correction(self, pasted: str) -> None:
        """Learn a spelling if the user fixes one word of what we just pasted."""
        try:
            from core.dictionary import observer_win

            observer_win.watch_for_correction(pasted, self._dictionary)
        except Exception as exc:  # pragma: no cover - COM/platform dependent
            print(f"[WinWhispr][autolearn] watcher unavailable: {exc}")

    def _vocab_for(self, raw_text: str) -> list:
        """Dictionary entries phonetically relevant to this utterance."""
        if self._dictionary is None:
            return []
        try:
            return [
                VocabEntry(entry.correct, tuple(entry.mishears))
                for entry in self._dictionary.prefilter(raw_text)
            ]
        except Exception as exc:  # pragma: no cover - store guard
            print(f"[WinWhispr][dictionary] prefilter failed: {exc}")
            return []

    def _finalize_session(self, full_text, raw_text, duration):
        """Log the whole session as one entry once dictation has stopped."""
        full_text = (full_text or "").strip()
        if not full_text:
            return
        words = len(full_text.split())
        commit = getattr(self, "_last_commit", None) or {}
        db_manager.log_entry(
            words,
            duration,
            text=full_text,
            app=commit.get("app"),
            raw_text=raw_text if commit.get("cleaned") else None,
            cleaned=bool(commit.get("cleaned")),
        )
        if self._on_note is not None:
            try:
                self._on_note(full_text, words, duration)
            except Exception as exc:  # pragma: no cover - callback guard
                print(f"[WinWhispr][hotkey] on_note callback failed: {exc}")

    def _emit_state(self, recording):
        if self._on_state is not None:
            try:
                self._on_state(recording)
            except Exception as exc:  # pragma: no cover - callback guard
                print(f"[WinWhispr][hotkey] on_state callback failed: {exc}")

    def _emit_llm_state(self, status):
        if self._on_llm_state is not None:
            try:
                self._on_llm_state(status)
            except Exception as exc:  # pragma: no cover - callback guard
                print(f"[WinWhispr][hotkey] on_llm_state callback failed: {exc}")

    def _emit_bar(self, state: BarState):
        if self._on_bar is not None:
            try:
                self._on_bar(state.value)
            except Exception as exc:  # pragma: no cover - callback guard
                print(f"[WinWhispr][hotkey] on_bar callback failed: {exc}")

    def _report(self, failure: Failure):
        """Surface a failure to the user instead of only to the console.

        Every one of these used to be a bare print in a window nobody sees,
        which is how "text isn't being typed" turns into an unexplainable bug.
        """
        diag = diagnose(failure)
        print(f"[WinWhispr][diag] {diag.headline}: {diag.detail}")
        if self._on_diagnostic is not None:
            try:
                self._on_diagnostic(diag.headline, diag.detail)
            except Exception as exc:  # pragma: no cover - callback guard
                print(f"[WinWhispr][hotkey] on_diagnostic callback failed: {exc}")

    def _load_reformatter(self):
        """Warm up the reformatter LLM in the background and report status."""
        self._emit_llm_state("loading")
        try:
            self._reformatter.load()
            self._emit_llm_state("ready")
            print("[WinWhispr] Reformatter LLM ready")
        except Exception as exc:  # pragma: no cover - runtime/model dependent
            print(f"[WinWhispr][reformat] LLM load failed: {exc}")
            self._emit_llm_state("error")

    def _on_reformat(self):
        """Hotkey handler: reformat the current selection / clipboard text."""
        with self._reformat_lock:
            if self._reformat_busy:
                return
            self._reformat_busy = True
        threading.Thread(target=self._reformat_worker, daemon=True).start()

    @staticmethod
    def _wait_modifiers_released(timeout=1.5):
        """Wait for the user to let go of the hotkey modifier keys.

        The reformat hotkey (e.g. ctrl+alt+r) means its modifiers are still held
        when the handler fires. Sending synthetic Ctrl+A / Ctrl+C / Ctrl+V while
        they are down (a) merges into the wrong combo so nothing is copied
        ("No text selected"), and (b) desyncs the OS modifier state, which stops
        later global hotkeys (dictation) from firing. Waiting for release fixes
        both.
        """
        mods = ("ctrl", "shift", "alt", "left windows", "right windows")
        end = time.time() + timeout
        while time.time() < end:
            try:
                if not any(keyboard.is_pressed(m) for m in mods):
                    return
            except Exception:
                return
            time.sleep(0.02)

    def _reformat_worker(self):
        original = None
        try:
            if self._reformatter.status != "ready":
                self._emit_llm_state("loading")
                self._reformatter.load()
                self._emit_llm_state("ready")

            # Capture which app is focused BEFORE we touch the clipboard, so the
            # LLM can align its output to that app (mail, editor, etc.).
            app_name = active_app_name()

            # Wait for the hotkey modifiers to be released so our synthetic
            # Ctrl+A/C/V are clean and don't leave modifiers stuck (which would
            # break the dictation hotkey afterwards).
            self._wait_modifiers_released()

            # Capture the entire text on screen: select all, then copy.
            original = pyperclip.paste()
            pyperclip.copy("")
            keyboard.send("ctrl+a")
            time.sleep(0.05)
            keyboard.send("ctrl+c")
            time.sleep(0.15)
            content = pyperclip.paste()
            if not content.strip():
                print("[WinWhispr][reformat] No text captured; nothing to reformat")
                pyperclip.copy(original)
                self._emit_llm_state("ready")
                return

            self._emit_llm_state("reformatting")
            result = self._reformatter.reformat(content, app_name=app_name)
            if result:
                pyperclip.copy(result)
                keyboard.send("ctrl+a")  # reselect all so paste replaces it
                time.sleep(0.05)
                keyboard.send(PASTE_HOTKEY)
                time.sleep(PASTE_SETTLE_SECONDS)
                pyperclip.copy(original)  # restore the user's clipboard
                print(f"[WinWhispr] Reformatted screen text (app: {app_name or 'unknown'})")
            else:
                pyperclip.copy(original)
            self._emit_llm_state("ready")
        except Exception as exc:  # pragma: no cover - runtime guard
            print(f"[WinWhispr][reformat] Reformat failed: {exc}")
            if original is not None:
                try:
                    pyperclip.copy(original)
                except Exception:
                    pass
            self._emit_llm_state("error")
        finally:
            with self._reformat_lock:
                self._reformat_busy = False

    # ---- state machine driver ---------------------------------------------
    #
    # Key handlers run on the `keyboard` library's hook thread. Anything slow
    # there (audio, ASR, clipboard) stalls system-wide keyboard input, so every
    # handler below does exactly one thing: put an event on the queue.

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000)

    def _post(self, event):
        self._events.put(event)

    def _on_key_event(self, event):
        """Raw keyboard hook: match on the event's own name.

        Not ``on_press_key``: that resolves a key name to scan codes, and
        ``key_to_scan_codes("right ctrl")`` includes 29 — which is LEFT ctrl.
        Hooking it made either Ctrl start dictation. The event's resolved name
        distinguishes them properly, and it also names AltGr as "alt gr"
        instead of the fake left-ctrl press Windows sends with it.
        """
        name = (getattr(event, "name", "") or "").lower()
        pressed = getattr(event, "event_type", None) == "down"

        if name == self._ptt_key:
            if pressed:
                if self._ptt_down:
                    return  # key auto-repeat, not a new press
                self._ptt_down = True
                self._post(Down(Binding.PUSH_TO_TALK, self._now_ms()))
            else:
                if not self._ptt_down:
                    return  # stray release (key was down before we hooked it)
                self._ptt_down = False
                self._post(Up(Binding.PUSH_TO_TALK, self._now_ms()))
            return

        if pressed and name == self._cancel_key:
            self._post(Cancel(self._now_ms()))

    def _on_trigger(self):
        """The legacy press-to-start / press-to-stop chord."""
        self._post(Down(Binding.HANDS_FREE, self._now_ms()))

    def _on_paste_last(self):
        threading.Thread(target=self._reuse_last, args=(True,), daemon=True).start()

    def _on_copy_last(self):
        threading.Thread(target=self._reuse_last, args=(False,), daemon=True).start()

    def _reuse_last(self, paste: bool):
        """Put the most recent transcript back on the clipboard (and paste it).

        Runs off the hook thread, and waits for the chord's modifiers to be
        released first — a synthetic Ctrl+V while Ctrl+Shift is still held
        merges into a different shortcut and pastes nothing.
        """
        try:
            notes = db_manager.get_notes(limit=1)
            if not notes:
                return
            text = notes[0]["text"]
            self._wait_modifiers_released()
            pyperclip.copy(text)
            if paste:
                keyboard.send(PASTE_HOTKEY)
            print(f"[WinWhispr] {'Pasted' if paste else 'Copied'} the last transcript")
        except Exception as exc:  # pragma: no cover - runtime guard
            print(f"[WinWhispr][hotkey] Could not reuse the last transcript: {exc}")

    def _machine_loop(self):
        """The only thread that touches the state machine."""
        while True:
            try:
                event = self._events.get(timeout=TICK_MS / 1000.0)
            except queue.Empty:
                # The queue timeout doubles as the machine's clock, so the
                # double-tap window and the session cap need no timer thread.
                event = Tick(self._now_ms())
            try:
                for action in self._machine.step(event):
                    self._apply(action)
            except Exception as exc:  # pragma: no cover - runtime guard
                print(f"[WinWhispr][state] action failed: {exc}")

    def _apply(self, action):
        if isinstance(action, StartCapture):
            self._begin_capture(action.session)
        elif isinstance(action, (StopCaptureAndFinalize, DiscardCapture)):
            if isinstance(action, DiscardCapture):
                self._discard.set()
            self._stop_event.set()
            self._emit_state(False)
        elif isinstance(action, ShowBar):
            self._emit_bar(action.state)
        elif isinstance(action, WarnSessionCap):
            print("[WinWhispr] Dictation has been running a long time; stopping soon.")
        elif isinstance(action, PlayPing):
            self._play_ping()
        elif isinstance(action, RunPipeline):
            # Implicit: the dictation thread finalizes itself once the stop
            # event is set, then posts Committed/Failed back to the machine.
            pass

    def _play_ping(self) -> None:
        """A short beep confirming the mic opened, for held-key dictation.

        Uses the system sound rather than a bundled WAV: no asset to ship, and
        it already respects whatever the user has set Windows sounds to.
        """
        if not self._sound_on_start:
            return
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        except Exception:  # pragma: no cover - platform/audio dependent
            pass

    def _begin_capture(self, session: int):
        thread = self._dictation_thread
        if thread is not None and thread.is_alive():
            # Should not happen: the machine only starts from Idle.
            return
        self._session = session
        self._discard.clear()
        self._stop_event.clear()
        self._dictation_thread = threading.Thread(
            target=self._dictation_loop, args=(session,), daemon=True
        )
        self._dictation_thread.start()
        self._emit_state(True)

    def toggle(self):
        """Programmatically start/stop dictation (same as pressing the hotkey)."""
        self._on_trigger()

    def is_recording(self):
        """Return True when a dictation session is active."""
        return self._machine.is_recording()

    def _register_hooks(self) -> None:
        """Install the global hooks. Raises if any of them fails."""
        if self._ptt_enabled:
            # One raw hook, never suppressing: the keys keep working normally
            # for every other app.
            keyboard.hook(self._on_key_event, suppress=False)
            print(f"[WinWhispr] Hold to talk: {self._ptt_key} "
                  f"({self._cancel_key} discards)")
        if self._toggle_enabled:
            keyboard.add_hotkey(self._hotkey, self._on_trigger)
            print(f"[WinWhispr] Toggle hotkey: {self._hotkey}")
        if self._reformat_hotkey:
            keyboard.add_hotkey(self._reformat_hotkey, self._on_reformat)
            print(f"[WinWhispr] Reformat hotkey: {self._reformat_hotkey}")
        if self._paste_last_hotkey:
            keyboard.add_hotkey(self._paste_last_hotkey, self._on_paste_last)
        if self._copy_last_hotkey:
            keyboard.add_hotkey(self._copy_last_hotkey, self._on_copy_last)

    def _run(self):
        """Install the hooks, retrying forever, then keep them alive.

        This used to try once and, on failure, give up for the rest of the run —
        indistinguishable from "the app is broken", with only a console message
        to explain it. Whatever blocks a global hook (an anti-cheat or security
        tool holding one) usually goes away, so keep retrying and say so once.
        """
        reported = False
        while True:
            try:
                self._register_hooks()
                break
            except Exception as exc:
                print(f"[WinWhispr][hotkey] Could not register hooks: {exc}")
                if not reported:
                    self._report(Failure.HOTKEY_HOOK_FAILED)
                    reported = True
                try:
                    keyboard.clear_all_hotkeys()
                except Exception:
                    pass
                time.sleep(HOOK_RETRY_SECONDS)
        if reported:
            print("[WinWhispr] Keyboard hooks recovered — dictation is live again.")
        keyboard.wait()  # Blocks this thread, keeping the hooks alive.

    def start(self):
        """Launch the listener on a background daemon thread."""
        self._key_thread = threading.Thread(target=self._key_worker, daemon=True)
        self._key_thread.start()

        self._machine_thread = threading.Thread(target=self._machine_loop, daemon=True)
        self._machine_thread.start()

        # Warm up the reformatter LLM without blocking dictation startup.
        self._llm_thread = threading.Thread(target=self._load_reformatter, daemon=True)
        self._llm_thread.start()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._thread
