from core.cleanup.normalize import (
    NL_SENTINEL,
    NP_SENTINEL,
    post_process,
    pre_normalize_layout,
)


def test_strips_code_fence():
    assert post_process("```\nHello world\n```") == "Hello world"
    assert post_process("```text\nHi there\n```") == "Hi there"


def test_converts_leftover_layout_cues():
    assert post_process("line one new line line two") == "line one\nline two"
    assert post_process("Para one. new paragraph Para two.") == "Para one.\n\nPara two."


def test_leaves_ordinary_text_alone():
    # "new design" is not a layout cue; "actually" is never touched here.
    s = "I actually really liked the new design."
    assert post_process(s) == s


def test_cue_needs_word_boundaries():
    # "newline" and "renew line" must not trigger a break.
    assert post_process("the newline character") == "the newline character"
    assert post_process("we renew licences") == "we renew licences"


def test_caps_blank_lines():
    assert post_process("a\n\n\n\nb") == "a\n\nb"


def test_pre_then_post_round_trips_layout_cues():
    norm = pre_normalize_layout("call me back at four thirty new line my desk number")
    assert NL_SENTINEL in norm
    assert post_process(norm) == "call me back at four thirty\nmy desk number"

    para = pre_normalize_layout("hey there new paragraph confirming friday")
    assert NP_SENTINEL in para
    assert post_process(para) == "hey there\n\nconfirming friday"


def test_longest_cue_wins():
    norm = pre_normalize_layout("done start a new paragraph next topic")
    assert NP_SENTINEL in norm
    assert NL_SENTINEL not in norm


def test_restores_model_emitted_sentinel():
    assert (
        post_process("Send me the address [[NL]] and the gate code.")
        == "Send me the address\nand the gate code."
    )
