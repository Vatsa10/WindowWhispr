# WinWhispr

Talk instead of typing. Hold a key, say your sentence, let go, and the words
appear wherever your cursor already was — in an email, a chat, a document, a
form, anything.

There is no model to download and nothing to configure. It works the minute it
is installed.

---

## Getting started

**1. Start WinWhispr.** A small button appears near the corner of your screen
saying *Tap to enable the microphone*. Tap it once and allow the microphone.
You only ever do this once.

**2. The button shrinks to a dot.** That dot is WinWhispr waiting. It sits in
the corner, faint, out of your way.

**3. Click into anything you can type in.** An email, a search box, a document.

**4. Hold `Right Ctrl`, say a sentence, and let go.** The dot grows into a pill
while you speak so you can see it is listening, and your words are typed at
your cursor a moment after you release the key.

That is the whole thing.

> **No Right Ctrl on your laptop?** Plenty do not have one. Open WinWhispr,
> go to **Dictation**, press **Change** next to *Talk key*, and hit whichever
> key you never use. Right Alt, Caps Lock and Menu are one tap away.

---

## The dot

WinWhispr is a dot in the corner of your screen whenever it is not being used.

| It looks like | It means |
| --- | --- |
| A faint grey dot | Waiting. Hold your talk key to start. |
| A green pill, pulsing | Listening. Your words appear in it as you speak. |
| A grey pill saying *Typing…* | Sending the words to your cursor. |
| A red dot | Something is wrong. Hover it to read what. |

- **Double-click the dot** to open WinWhispr's window.
- **Right-click it** for *Quit* and *Keep running*.
- **Drag it** anywhere you like, or set its corner in **Dictation**.

The dot has to stay on screen — it is what does the listening, and Windows
stops a hidden window from hearing anything. Keeping it small and faint is the
next best thing.

---

## Everyday use

**Dictate anywhere.** WinWhispr types into whatever window has focus, so it
works in apps that have no dictation of their own.

**Speak your punctuation.** Say "comma", "full stop", "question mark" or "new
line" and you get the real thing.

**Cancel a sentence.** Press `Esc` while you are still holding the talk key and
nothing is typed.

**Talk without holding the key.** Turn on *Tap twice to keep listening* in
**Dictation**. Tap the talk key twice and it keeps going until you tap again.

**Fix a name it keeps getting wrong.** Open **Dictionary**, type the correct
spelling and the way it comes out wrong. From then on it is corrected
automatically. Only the exact words you list are ever changed.

**See what you have said.** **Activity** keeps every transcript, searchable,
with the app it went into — plus your words per minute and how much time you
have saved. It never leaves your machine.

---

## The window

Double-click the dot, or click the tray icon, to open WinWhispr. Five tabs:

| Tab | What is in it |
| --- | --- |
| **Dictation** | Your language, your talk key, and where the dot sits |
| **Cleanup** | Whether transcripts are tidied before they are typed |
| **Dictionary** | Names and words it keeps mishearing |
| **Activity** | Your transcripts, and how much you have dictated |
| **Storage** | Start with Windows, and erasing your history |

Closing the window does not close WinWhispr. It keeps running so your talk key
is always ready. To close it properly, right-click the dot and choose **Quit**,
or use the tray icon.

---

## What it does to your words

Speech comes out messier than writing, so WinWhispr tidies each sentence before
typing it. Fixed rules, not a model, so the result is the same every time and
nothing is ever invented:

- fillers removed — "um", "uh", "you know", repeated words
- spoken punctuation applied
- sentences capitalised, spacing fixed
- your dictionary corrections applied
- your snippets expanded

Turn all of it off in **Cleanup** if you would rather have exactly what you
said.

---

## Things worth knowing

**It needs an internet connection.** WinWhispr uses the speech recognition
already built into Windows rather than shipping its own model, and that service
does the transcribing on its own servers. Your audio goes there and nowhere
else. Your transcripts, settings and dictionary stay on your machine.

**It only listens while you hold the key.** Nothing is recorded in the
background, and the dot turns green whenever the microphone is open, so you can
always see it.

**It needs Microsoft Edge.** The recognizer runs in an Edge window of its own,
because Edge is the only host on Windows with a working speech service behind
it -- WebView2, which ships the same engine, has the microphone but not the
service and fails every attempt with a network error. Windows comes with Edge,
so this is only a problem if you have removed it. WinWhispr uses a profile of
its own: your own Edge windows, history and session are never touched.

**Some apps need Administrator.** Windows will not let a normal program see key
presses inside an elevated app. If your talk key does nothing in one particular
program, run WinWhispr as Administrator.

Your settings live in `%USERPROFILE%\.cache\winwhispr`.

---

## Installing

### The quick way

1. Open the [latest release](https://github.com/Vatsa10/WindowWhispr/releases/latest).
2. Download **WinWhispr-Setup.exe**.
3. Run it. No administrator password: it installs for you only.

WinWhispr appears in the Start Menu, so typing its name finds it, and in
**Add or remove programs** for when you want it gone.

**Prefer not to install anything?** Download **WinWhispr-Portable.zip**
instead, extract it somewhere permanent (your Downloads folder is not
permanent) and run **WinWhispr.exe**. Nothing is registered with Windows, so
it will not turn up in search until you switch on **Show WinWhispr in the
Start Menu** in the app's **Storage** tab.

Windows will warn you that it does not recognise the app. It says this about
every program without a paid code-signing certificate, which this does not yet
have. Choose **More info**, then **Run anyway**. If you would rather not take
that on trust, build it yourself from source below; it is the same program.

WinWhispr starts in the system tray with a small button near the corner of your
screen. Tap it once to allow the microphone and you are done.

### Removing it

Uninstall from **Add or remove programs**, or from the Start Menu entry. It
deletes the program folder completely and removes the sign-in entry if you
turned that on, then asks whether to delete your settings, dictionary and
history as well. Answer No and a future reinstall picks up where you left off.

If you used the zip, delete the folder you extracted. Your settings live
separately, in `%USERPROFILE%\.cache\winwhispr`; delete that folder too if you
want nothing left behind.

### Upgrading

Your settings, dictionary and history survive an upgrade. Run the new installer
over the top, or replace the extracted folder with the new one.

WinWhispr checks for a newer release once a day and tells you in a notification
when there is one. It never downloads or installs anything by itself.

### Building it yourself

```powershell
git clone https://github.com/Vatsa10/WindowWhispr.git
cd WindowWhispr
uv sync
uv run winwhispr
```

You need [Python 3.10+](https://www.python.org/downloads/) and
[`uv`](https://docs.astral.sh/uv/).

To produce the same portable folder the release contains:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

It lands in `dist\WinWhispr\`. Add `-Installer` to build a setup executable
instead, which additionally needs
[Inno Setup 6](https://jrsoftware.org/isinfo.php).

### Other ways to start it

```powershell
uv run python main.py listen     # dictation only, no settings window
uv run python main.py web        # dictate from a phone or another laptop
```

## Dictate from your phone

```powershell
uv run python main.py web --lan --allow-paste
```

Open the printed address on your phone and tap the button. Your phone becomes
the microphone and your PC gets the words. `--lan` prints an access token the
page asks for once, because that address can type into your machine and a
shared network is not a trusted one.

---

## If something is not working

**"Speech service refused", or nothing is transcribed though the dot turns
green.** First check Microsoft Edge is installed: the recognizer runs in an
Edge window and there is no fallback without one. If it is, open **Settings >
Privacy & security > Speech** and turn on **Online speech recognition**.

**The talk key does nothing.** Check the dot is there and grey rather than red.
If the app you are typing into runs as Administrator, WinWhispr has to as well.

**"Microphone blocked".** Windows or Edge has denied the microphone. Allow it
in **Settings → Privacy → Microphone**, then click the dot to try again.

**Nothing was heard.** The dot turns green when the microphone is open — if it
does not, the wrong input device is selected in Windows sound settings.

**It stopped mid-sentence.** Long pauses end a take. Keep talking, or turn on
*Tap twice to keep listening*.

The log is at `%USERPROFILE%\.cache\winwhispr\logs\winwhispr.log` and is the
first place to look for anything else.

---

## For developers

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, including why
the recognizer lives in its own window and why that window cannot be hidden.

```powershell
uv run --extra dev pytest
```

The suite is pure logic — no Qt, no keyboard hooks, no microphone, no models —
so it runs anywhere in a second or two. The cleanup rules, dictionary
corrections, key-binding rules, pill geometry, dictation state machine and
stats maths all have tests that define the behaviour rather than merely cover
it. The JavaScript halves of caret insertion and key binding are tested as
JavaScript, through Node, rather than as Python translations of themselves.

## Credits

The transcript cleanup design — the rules, the deterministic gates, the
push-to-talk state machine, the dictionary, and the overlay pill — began as a
Python translation of logic from **WhimprFlow**, an MIT-licensed Rust/Tauri
dictation proof of concept. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the file-by-file mapping
and the original license.

## License

MIT — see [LICENSE](LICENSE).
