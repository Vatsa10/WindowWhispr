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


def test_ignores_lowercase_replacements():
    # Names are capitalized; a lowercase fix is just an edit.
    assert detect_correction("the widgit is here", "the widget is here") is None


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
