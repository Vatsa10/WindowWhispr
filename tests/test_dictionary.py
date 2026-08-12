import pytest

from core.dictionary import SOURCE_AUTO, SOURCE_MANUAL, DictionaryStore
from core.dictionary.similarity import close, normalized_distance


@pytest.fixture()
def store(tmp_path):
    return DictionaryStore(tmp_path / "dictionary.json")


def test_add_and_persist(store, tmp_path):
    assert store.add("Manvi", ["Monvi", "Manvee"])
    reloaded = DictionaryStore(tmp_path / "dictionary.json").load()
    entry = reloaded.entries()[0]
    assert entry.correct == "Manvi"
    assert entry.mishears == ["Monvi", "Manvee"]
    assert entry.source == SOURCE_MANUAL


def test_add_merges_case_insensitively(store):
    store.add("ChargeBee", ["charge bee"])
    store.add("chargebee", ["Charge B"])
    assert len(store.entries()) == 1
    assert store.entries()[0].mishears == ["charge bee", "Charge B"]


def test_add_does_not_duplicate_known_mishears(store):
    store.add("Manvi", ["Monvi"])
    assert store.add("Manvi", ["monvi"]) is False
    assert store.entries()[0].mishears == ["Monvi"]


def test_auto_learn_does_not_demote_a_manual_entry(store):
    store.add("Manvi", source=SOURCE_MANUAL)
    store.add("Manvi", ["Monvi"], source=SOURCE_AUTO)
    assert store.entries()[0].source == SOURCE_MANUAL


def test_remove(store):
    store.add("Manvi")
    assert store.remove("manvi")
    assert store.entries() == []
    assert store.remove("nothing") is False


def test_prefilter_matches_a_close_mishear(store):
    store.add("Manvi", ["Monvi"])
    assert [e.correct for e in store.prefilter("send it to monvi")] == ["Manvi"]


def test_prefilter_catches_a_split_word(store):
    # Recognition hears two words; the adjacent-pair gram rejoins them.
    store.add("ChargeBee")
    assert [e.correct for e in store.prefilter("the charge bee invoice")] == ["ChargeBee"]


def test_prefilter_ignores_unrelated_utterances(store):
    store.add("Manvi", ["Monvi"])
    assert store.prefilter("lets meet on friday afternoon") == []


def test_prefilter_respects_the_cap(store):
    for i in range(30):
        store.add(f"Zeta{i}")
    assert len(store.prefilter("zeta0 " * 5, max_entries=15)) <= 15


def test_missing_and_corrupt_files_load_empty(tmp_path):
    assert DictionaryStore(tmp_path / "nope.json").load().entries() == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert DictionaryStore(bad).load().entries() == []


def test_similarity_threshold():
    assert close("monvi", "manvi")
    assert normalized_distance("abc", "abc") == 0.0
    assert not close("friday", "manvi")
