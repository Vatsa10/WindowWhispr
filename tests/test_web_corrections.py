"""The personal dictionary, applied to a browser transcript.

The browser's recognizer takes no vocabulary hints, so the dictionary can only
be applied after the fact. Replacement after the fact can corrupt words the
user really did say, which is the one failure this app is not allowed to have,
so the rules are narrow and pinned here.
"""

from core.web.corrections import MIN_MISHEAR_CHARS, apply, build_rules


class _Entry:
    def __init__(self, correct, mishears=(), source="manual"):
        self.correct = correct
        self.mishears = list(mishears)
        self.source = source


def _rules(*entries):
    return build_rules(entries)


def test_a_known_mishear_is_corrected():
    assert apply("send the charge bee invoice",
                 _rules(_Entry("ChargeBee", ["charge bee"]))) == "send the ChargeBee invoice"


def test_only_whole_words_are_replaced():
    """The failure that makes find-and-replace dangerous."""
    rules = _rules(_Entry("Vatsa", ["watson"]))
    assert apply("I wonder about watsonville", rules) == "I wonder about watsonville"
    assert apply("watsons", rules) == "watsons"
    assert apply("ask watson", rules) == "ask Vatsa"


def test_a_capitalised_mishear_keeps_its_capital():
    # Otherwise a sentence that started with the word comes back lowercase.
    rules = _rules(_Entry("chargebee", ["charge bee"]))
    assert apply("Charge bee is down", rules) == "Chargebee is down"


def test_the_correct_spelling_wins_over_how_it_was_heard():
    assert apply("CHARGE BEE", _rules(_Entry("ChargeBee", ["charge bee"]))) == "ChargeBee"


def test_the_longest_mishear_wins():
    """Otherwise a short rule eats half of what a longer one would have fixed."""
    rules = _rules(_Entry("ChargeBee", ["charge", "charge bee"]))
    assert apply("the charge bee bill", rules) == "the ChargeBee bill"


def test_very_short_mishears_are_ignored():
    """Two letters match far too much ordinary English to replace safely."""
    assert MIN_MISHEAR_CHARS >= 3
    assert apply("a be c", _rules(_Entry("ChargeBee", ["be"]))) == "a be c"


def test_an_entry_with_no_mishears_changes_nothing():
    assert apply("nothing to do", _rules(_Entry("ChargeBee"))) == "nothing to do"


def test_a_mishear_equal_to_the_correction_is_not_a_rule():
    # It would be a no-op at best and a capitalisation flip at worst.
    assert build_rules([_Entry("ChargeBee", ["chargebee"])]) == []


def test_an_empty_dictionary_leaves_the_text_alone():
    assert apply("untouched", []) == "untouched"
    assert apply("", _rules(_Entry("X", ["yyy"]))) == ""


def test_punctuation_around_a_mishear_survives():
    rules = _rules(_Entry("ChargeBee", ["charge bee"]))
    assert apply("is charge bee, or not?", rules) == "is ChargeBee, or not?"
