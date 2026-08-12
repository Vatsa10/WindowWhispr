"""Gate assertions, ported from WhimprFlow's gates.rs test suite.

These *are* the spec for what cleanup is allowed to do to a transcript.
"""

from core.cleanup.gates import GateReason, evaluate, must_preserve_entities, novelty_ratio
from core.cleanup.levels import CleanupLevel

LIGHT = CleanupLevel.LIGHT
MEDIUM = CleanupLevel.MEDIUM
HIGH = CleanupLevel.HIGH


def test_light_cleanup_passes():
    raw = "um so i think we should uh meet at 3"
    clean = "So I think we should meet at 3."
    assert evaluate(raw, clean, LIGHT).passed


def test_dropping_a_long_number_fails():
    raw = "transfer 500 dollars to account 12345"
    clean = "Transfer money to the account."
    verdict = evaluate(raw, clean, LIGHT)
    assert not verdict.passed
    assert verdict.reason is GateReason.LOST_ENTITY


def test_short_numbers_are_not_protected():
    # A self-correction legitimately drops "2"; protecting 1-3 digit numbers
    # made the gate reject good cleanups.
    raw = "lets meet at 2 actually 3"
    clean = "Let's meet at 3."
    assert evaluate(raw, clean, LIGHT).passed


def test_urls_and_emails_must_survive():
    raw = "email me at vatsa@example.com about wisprflow.com"
    assert set(must_preserve_entities(raw)) == {"vatsa@example.com", "wisprflow.com"}
    assert not evaluate(raw, "Email me about the site.", LIGHT).passed


def test_answering_a_question_is_banned():
    raw = "what time is the standup"
    clean = "Here is the standup schedule: 9am."
    verdict = evaluate(raw, clean, LIGHT)
    assert not verdict.passed
    assert verdict.reason is GateReason.BANNED_PATTERN


def test_banned_prefix_already_in_raw_is_allowed():
    # The speaker actually said it, so it is their words, not the model's.
    raw = "sure, that works for me"
    clean = "Sure, that works for me."
    assert evaluate(raw, clean, LIGHT).passed


def test_over_deletion_fails():
    raw = "the quarterly report is due on friday please review the budget section"
    clean = "Report due Friday."
    verdict = evaluate(raw, clean, MEDIUM)
    assert not verdict.passed
    assert verdict.reason is GateReason.OVER_DELETION


def test_hallucinated_growth_fails():
    raw = "send it tomorrow"
    clean = (
        "Please send the completed document tomorrow morning before the "
        "deadline, and let me know once it is done."
    )
    verdict = evaluate(raw, clean, HIGH)
    assert not verdict.passed
    assert verdict.reason is GateReason.HALLUCINATION


def test_mild_rewrite_passes_light_but_heavy_one_does_not():
    raw = "i went to the store and then i bought some milk and eggs and bread"
    mild = "I went to the store and bought milk, eggs, and bread."
    heavy = "Purchased dairy and bakery goods."
    assert evaluate(raw, mild, LIGHT).passed
    assert not evaluate(raw, heavy, LIGHT).passed


def test_none_level_always_passes():
    assert evaluate("anything", "totally different", CleanupLevel.NONE).passed


def test_novelty_ignores_case_and_punctuation_and_deletions():
    # Only *new* words count; dropping fillers is free.
    assert novelty_ratio("um so i think", "So I think.") == 0.0
