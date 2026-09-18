"""Rules-only cleanup: what it must fix, and what it must leave alone.

The second half matters more than the first. A rule that damages correct text
is worse than no rule, because the user cannot see what was taken away.
"""

from core.cleanup.deterministic import (
    apply_spoken_punctuation,
    capitalize_sentences,
    clean,
    collapse_stutters,
    remove_fillers,
)


def test_removes_hesitations():
    # "so" opening the sentence is throat-clearing and goes too.
    assert remove_fillers("um so I uh think") == "I think"
    assert remove_fillers("the um report") == "the report"


def test_removes_throat_clearing_only_at_a_sentence_start():
    assert clean("so I think we should go") == "I think we should go"
    # "so" mid-sentence is meaningful and must survive.
    assert "so" in clean("I went early so I could park").lower()


def test_collapses_stutters():
    assert collapse_stutters("the the team") == "the team"
    assert collapse_stutters("I I I think") == "I think"


def test_keeps_deliberate_repetition():
    assert collapse_stutters("no no that's fine") == "no no that's fine"
    assert collapse_stutters("it had had an effect") == "it had had an effect"


def test_spoken_punctuation_becomes_marks():
    assert apply_spoken_punctuation("that works period").strip() == "that works."
    assert apply_spoken_punctuation("does that work question mark").strip() == "does that work?"


def test_punctuation_words_used_as_nouns_survive():
    # "the period" is a noun phrase, not an instruction.
    assert "period" in apply_spoken_punctuation("the period drama was good")
    assert "comma" in apply_spoken_punctuation("a comma splice")


def test_spoken_line_breaks_become_real_ones():
    """The README promises this, so it has to be true."""
    assert apply_spoken_punctuation("first line new line second line") == (
        "first line\nsecond line")
    assert apply_spoken_punctuation("one new paragraph two") == "one\n\ntwo"


def test_a_line_break_survives_the_whole_pipeline():
    """Spacing and capitalisation both run after it and both touch newlines."""
    assert clean("thanks new line priya") == "Thanks\nPriya"


def test_new_line_as_a_noun_survives():
    """"a new line of code" is a thing people say."""
    assert "new line" in clean("i wrote a new line of code")


def test_a_word_ending_in_a_does_not_swallow_the_punctuation():
    """The guard against "a comma" must not also match "Priya comma".

    It did, for every name or noun ending in "a" -- anna, dana, data, idea,
    area -- which silently turned dictated punctuation back into words.
    """
    assert clean("tell priya comma then go") == "Tell priya, then go"
    assert clean("see anna full stop") == "See anna."
    assert clean("the data period") == "The data."


def test_capitalizes_sentences_and_the_pronoun_i():
    assert capitalize_sentences("i went. then i left.") == "I went. Then I left."


def test_full_pipeline_on_a_realistic_utterance():
    raw = "um so i think we should uh meet at three period does that work question mark"
    assert clean(raw) == "I think we should meet at three. Does that work?"


def test_leaves_clean_text_untouched():
    text = "I actually really liked the new design."
    assert clean(text) == text


def test_does_not_invent_content_for_empty_input():
    assert clean("") == ""
    assert clean("   ") == ""


def test_preserves_numbers_names_and_urls():
    raw = "email vatsa at winwhispr dot com about order 12345"
    out = clean(raw)
    assert "12345" in out
    assert "vatsa" in out.lower()


def test_self_corrections_are_left_for_the_model():
    # Rules must not guess at meaning: "actually" here is a correction, but
    # deciding that needs context, so the words stay and the LLM (if enabled)
    # gets the chance.
    out = clean("meet at 2 actually 3")
    assert "2" in out and "3" in out
