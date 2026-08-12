from core.commands import parse
from core.snippets import expand, load, save


def test_trailing_command_is_stripped_and_returned():
    result = parse("send it to the team, press enter")
    assert result.text == "send it to the team"
    assert result.key == "enter"


def test_trailing_punctuation_does_not_hide_the_cue():
    assert parse("looks good. Press enter.").key == "enter"


def test_mid_sentence_mention_is_left_alone():
    result = parse("then press enter on the form")
    assert result.key is None
    assert result.text == "then press enter on the form"


def test_command_only_utterance_pastes_nothing():
    result = parse("press enter")
    assert result.text == ""
    assert result.key == "enter"


def test_plain_text_is_untouched():
    result = parse("meeting at three")
    assert result.text == "meeting at three"
    assert result.key is None


def test_cue_must_be_its_own_phrase():
    # "compress enter" ends with "s enter", not the standalone cue.
    assert parse("the file will decompress enter").key is None


def test_snippet_expansion():
    table = {"my sign off": "Best,\nVatsa"}
    assert expand("thanks, my sign off", table) == "thanks, Best,\nVatsa"


def test_longest_trigger_wins():
    table = {"my email": "a@x.com", "my work email": "b@y.com"}
    assert expand("send to my work email", table) == "send to b@y.com"


def test_partial_words_are_not_expanded():
    table = {"addr": "12 Main St"}
    assert expand("the address is here", table) == "the address is here"


def test_expansion_without_a_table_is_a_no_op():
    assert expand("nothing to do", {}) == "nothing to do"


def test_snippet_round_trip(tmp_path):
    path = tmp_path / "snippets.json"
    save(path, {"sig": "Vatsa"})
    assert load(path) == {"sig": "Vatsa"}


def test_missing_and_corrupt_snippet_files(tmp_path):
    assert load(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert load(bad) == {}
