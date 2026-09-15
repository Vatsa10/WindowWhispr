from core.dictionary.autolearn import detect_correction, word_tokens


def test_learns_a_corrected_name():
    found = detect_correction("send it to Monvi tonight", "send it to Manvi tonight")
    assert found is not None
    assert (found.mishear, found.correct) == ("Monvi", "Manvi")


def test_ignores_ordinary_word_swaps():
    # "their" is in the stoplist: this is a normal edit, not a spelling lesson.
    assert detect_correction("there books are here", "their books are here") is None


def test_ignores_multi_word_changes():
    assert detect_correction("meet at the cafe", "see you at the diner") is None


def test_ignores_short_words():
    assert detect_correction("go to Al now", "go to Ed now") is None


def test_ignores_case_only_edits():
    assert detect_correction("call manvi later", "call Manvi later") is None


def test_ignores_unrelated_replacements():
    # Too far apart to be the same word misheard.
    assert detect_correction("the foo is ready", "the Xylophone is ready") is None


def test_learns_lowercase_corrections_now():
    """Capitalisation used to be required, which blocked every lowercase
    technical term -- kubectl, jsonl, npm could never be learned. The guard
    against learning ordinary English is the word lists, not a capital letter.
    """
    found = detect_correction("the widgit is here", "the widget is here")
    assert found is not None
    assert (found.mishear, found.correct) == ("widgit", "widget")


def test_ignores_no_change():
    assert detect_correction("nothing changed here", "nothing changed here") is None


def test_ignores_pure_reordering():
    assert detect_correction("Manvi and Ravi", "Ravi and Manvi") is None


def test_ignores_non_alphabetic():
    assert detect_correction("order A123 shipped", "order B456 shipped") is None


def test_empty_input_is_safe():
    assert detect_correction("", "anything") is None
    assert detect_correction("anything", "") is None


def test_word_tokens_trim_punctuation():
    assert word_tokens("Hi, Manvi! (really)") == ["Hi", "Manvi", "really"]


# --- the widened shapes (spec 2026-09-12 §6) ------------------------------


def test_two_words_becoming_one_is_detected():
    """"charge bee" -> "ChargeBee" is the case this module is written around."""
    found = detect_correction("call charge bee today", "call ChargeBee today")
    assert found is not None
    assert (found.mishear, found.correct) == ("charge bee", "ChargeBee")


def test_one_word_becoming_two_is_detected():
    found = detect_correction("open kubectl now", "open kube ctl now")
    assert found is not None
    assert found.mishear == "kubectl"


def test_a_lowercase_technical_term_is_detected():
    """Requiring a capital blocked every lowercase term outright."""
    found = detect_correction("run cube ctl apply", "run kubectl apply")
    assert found is not None
    assert found.correct == "kubectl"


def test_two_separate_edits_are_not_one_correction():
    assert detect_correction("alpha beta", "gamma delta") is None


def test_an_everyday_misspelling_is_not_learned():
    # Real, but it teaches nothing about a name, and the dictionary is for names.
    assert detect_correction("i recieve it", "i receive it") is None


def test_stoplist_words_are_still_refused():
    assert detect_correction("meet them their", "meet them there") is None


def test_a_case_only_edit_is_still_refused():
    assert detect_correction("Manvi is here", "manvi is here") is None
