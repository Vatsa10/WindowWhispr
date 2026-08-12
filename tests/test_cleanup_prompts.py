from core.cleanup import (
    CleanupContext,
    VocabEntry,
    assemble_user_message,
    build_messages,
)
from core.cleanup.levels import CleanupLevel
from core.cleanup.prompts import FEW_SHOT, format_mode_for_app, system_for


def test_message_shape():
    msgs = build_messages("hello", CleanupContext())
    assert len(msgs) == 1 + 2 * len(FEW_SHOT) + 1
    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"
    # Few-shot turns must alternate user/assistant or the model reads them wrong.
    for i, msg in enumerate(msgs[1:-1]):
        assert msg.role == ("user" if i % 2 == 0 else "assistant")


def test_few_shot_can_be_capped():
    # Hosted models get a trimmed prompt: the free tier's real ceiling is
    # tokens per minute, so demonstrations they do not need cost throughput.
    msgs = build_messages("hello", CleanupContext(), few_shot=4)
    assert len(msgs) == 1 + 2 * 4 + 1
    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"


def test_few_shot_zero_still_sends_the_transcript():
    msgs = build_messages("hello", CleanupContext(), few_shot=0)
    assert len(msgs) == 2
    assert "hello" in msgs[-1].content


def test_few_shot_keeps_the_anti_over_edit_anchors():
    outputs = [out for _, out in FEW_SHOT]
    assert "I actually really liked the new design." in outputs
    assert any(o.startswith("I think the demo went well") for o in outputs)


def test_user_message_wraps_transcript_and_vocab():
    ctx = CleanupContext(vocab=[VocabEntry("Manvi", ("Monvi",))])
    msg = assemble_user_message("send it to monvi", ctx)
    assert "<CUSTOM_VOCABULARY>" in msg
    assert "Manvi  (mis-heard as: Monvi)" in msg
    assert "<USER_MESSAGE>\nsend it to monvi\n</USER_MESSAGE>" in msg


def test_placeholder_context_is_dropped():
    ctx = CleanupContext(window_context="Reply...", app_name="slack")
    assert "WINDOW_CONTEXT" not in assemble_user_message("hello", ctx)

    ctx = CleanupContext(window_context="two words", app_name="slack")
    assert "WINDOW_CONTEXT" not in assemble_user_message("hello", ctx)


def test_real_context_is_kept():
    ctx = CleanupContext(window_context="the launch plan for next quarter", app_name="slack")
    msg = assemble_user_message("hello", ctx)
    assert "<WINDOW_CONTEXT>" in msg
    assert "App: slack" in msg


def test_format_mode_uses_windows_exe_names():
    # active_app_name() returns an exe basename, e.g. "OUTLOOK", not a bundle id.
    assert "EMAIL" in format_mode_for_app("OUTLOOK")
    assert "TEAM CHAT" in format_mode_for_app("slack")
    assert "TEAM CHAT" in format_mode_for_app("ms-teams")
    assert "DOCUMENT" in format_mode_for_app("WINWORD")
    assert "DIRECT message" in format_mode_for_app("WhatsApp")
    # Browsers are ambiguous (Gmail? Docs? anything) so they get no adaptation.
    assert format_mode_for_app("chrome") is None
    assert format_mode_for_app("msedge") is None
    assert format_mode_for_app(None) is None


def test_system_prompt_composition():
    # The base prompt *mentions* a Formatting Mode section; only the appended
    # header means one was actually supplied.
    header = "# Formatting Mode (follow this for structure and tone)"
    plain = system_for(CleanupLevel.LIGHT)
    assert "Be conservative" in plain
    assert header not in plain

    outlook = system_for(CleanupLevel.LIGHT, "OUTLOOK")
    assert header in outlook
    assert "Target is EMAIL" in outlook


def test_levels_ceilings():
    assert CleanupLevel.NONE.bypasses_llm()
    assert not CleanupLevel.LIGHT.bypasses_llm()
    assert CleanupLevel.NONE.max_novelty_ratio() == 0.0
    assert CleanupLevel.LIGHT.max_novelty_ratio() == 0.34
    assert CleanupLevel.MEDIUM.max_novelty_ratio() == 0.55
    assert CleanupLevel.HIGH.max_novelty_ratio() == 0.85


def test_level_parse_is_lenient():
    assert CleanupLevel.parse("HIGH") is CleanupLevel.HIGH
    assert CleanupLevel.parse("nonsense") is CleanupLevel.LIGHT
    assert CleanupLevel.parse(CleanupLevel.NONE) is CleanupLevel.NONE
