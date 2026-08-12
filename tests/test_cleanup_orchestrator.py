"""The orchestrator's one promise: the user's words never disappear."""

import time

from core.cleanup import CleanupContext
from core.cleanup.levels import CleanupLevel
from core.cleanup.orchestrator import run_cleanup
from core.cleanup.provider_local import render_chatml, strip_envelope


class FakeProvider:
    def __init__(self, output="", raises=None, delay=0.0):
        self.output = output
        self.raises = raises
        self.delay = delay
        self.calls = 0

    def cleanup(self, messages):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        return self.output


RAW = "um so i think we should uh meet at 3"


def test_happy_path_returns_cleaned_text():
    provider = FakeProvider("So I think we should meet at 3.")
    result = run_cleanup(RAW, CleanupContext(), provider)
    assert result.text == "So I think we should meet at 3."
    assert not result.used_raw


def test_gate_failure_falls_back_to_raw():
    provider = FakeProvider("Here is the meeting schedule: 9am.")
    result = run_cleanup("what time is the standup", CleanupContext(), provider)
    assert result.used_raw
    assert result.reason.startswith("gate:")
    assert result.text == "what time is the standup"


def test_provider_error_falls_back_to_raw():
    provider = FakeProvider(raises=RuntimeError("model exploded"))
    result = run_cleanup(RAW, CleanupContext(), provider)
    assert result.used_raw and result.text == RAW


def test_timeout_falls_back_to_raw():
    provider = FakeProvider("whatever", delay=0.3)
    result = run_cleanup(RAW, CleanupContext(), provider, timeout_ms=50)
    assert result.used_raw and result.reason == "timeout"
    assert result.text == RAW


def test_empty_model_output_falls_back_to_raw():
    result = run_cleanup(RAW, CleanupContext(), FakeProvider("   "))
    assert result.used_raw and result.text == RAW


def test_level_none_skips_the_model_entirely():
    provider = FakeProvider("should never run")
    ctx = CleanupContext(level=CleanupLevel.NONE)
    result = run_cleanup(RAW, ctx, provider)
    assert provider.calls == 0
    assert result.used_raw and result.text == RAW


def test_fallback_never_contains_a_sentinel():
    provider = FakeProvider(raises=RuntimeError("boom"))
    result = run_cleanup("call me new line at four", CleanupContext(), provider)
    assert "[[NL]]" not in result.text
    assert result.text == "call me\nat four"


def test_missing_provider_is_not_an_error():
    result = run_cleanup(RAW, CleanupContext(), None)
    assert result.used_raw and result.text == RAW


def test_chatml_rendering_primes_the_assistant():
    msgs = [type("M", (), {"role": "system", "content": "hi"})()]
    rendered = render_chatml(msgs)
    assert rendered.startswith("<|im_start|>system\nhi<|im_end|>")
    assert rendered.endswith("<|im_start|>assistant\n")


def test_strip_envelope_removes_scaffolding():
    assert strip_envelope("Hello.<|im_end|>\n<|im_start|>user") == "Hello."
    assert strip_envelope("<USER_MESSAGE>\nHi\n</USER_MESSAGE>") == "Hi"
