"""Learning a correction, and only after it repeats.

One sighting proves nothing -- people fix typos and rewrite sentences. Two is a
pattern. These pin that line, and the expiry that stops two unrelated typos
months apart from adding up to one.
"""

from datetime import timedelta

from core.dictionary import MAX_VOCAB, SOURCE_AUTO, SOURCE_MANUAL, DictionaryStore
from core.dictionary.autolearn import Correction
from core.dictionary.promotion import (
    EXPIRE_AFTER,
    PROMOTE_AT,
    Pending,
    PendingStore,
    _now,
    observe,
)


def _stores(tmp_path):
    return (PendingStore(tmp_path / "pending.json").load(),
            DictionaryStore(tmp_path / "dictionary.json").load())


def test_one_sighting_does_not_promote(tmp_path):
    pending, dictionary = _stores(tmp_path)
    assert observe(Correction("monvi", "Manvi"), pending, dictionary) is False
    assert dictionary.entries() == []
    assert [r.count for r in pending.rows()] == [1]


def test_the_second_sighting_promotes(tmp_path):
    pending, dictionary = _stores(tmp_path)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    assert observe(Correction("monvi", "Manvi"), pending, dictionary) is True

    entry = dictionary.entries()[0]
    assert entry.correct == "Manvi"
    assert "monvi" in entry.mishears
    assert entry.source == SOURCE_AUTO


def test_a_promoted_row_stops_being_pending(tmp_path):
    """Otherwise it would promote again on every later sighting."""
    pending, dictionary = _stores(tmp_path)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    assert pending.rows() == []


def test_two_different_corrections_do_not_add_up(tmp_path):
    pending, dictionary = _stores(tmp_path)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    observe(Correction("charge bee", "ChargeBee"), pending, dictionary)
    assert dictionary.entries() == []
    assert len(pending.rows()) == 2


def test_an_expired_sighting_is_dropped_rather_than_counted(tmp_path):
    pending, dictionary = _stores(tmp_path)
    stale = _now() - EXPIRE_AFTER - timedelta(days=1)
    pending.record("monvi", "Manvi", now=stale)

    # The same correction again, long after: a fresh start, not a promotion.
    assert observe(Correction("monvi", "Manvi"), pending, dictionary) is False
    assert dictionary.entries() == []
    assert [r.count for r in pending.rows()] == [1]


def test_a_sighting_inside_the_window_still_counts(tmp_path):
    pending, dictionary = _stores(tmp_path)
    recent = _now() - EXPIRE_AFTER + timedelta(days=1)
    pending.record("monvi", "Manvi", now=recent)
    assert observe(Correction("monvi", "Manvi"), pending, dictionary) is True


def test_promotion_never_demotes_something_typed_by_hand(tmp_path):
    pending, dictionary = _stores(tmp_path)
    dictionary.add("Manvi", ["manvee"], source=SOURCE_MANUAL)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    observe(Correction("monvi", "Manvi"), pending, dictionary)
    assert dictionary.entries()[0].source == SOURCE_MANUAL


def test_a_correction_to_itself_is_ignored(tmp_path):
    pending, dictionary = _stores(tmp_path)
    assert observe(Correction("Manvi", "manvi"), pending, dictionary) is False
    assert pending.rows() == []


def test_nothing_detected_changes_nothing(tmp_path):
    pending, dictionary = _stores(tmp_path)
    assert observe(None, pending, dictionary) is False


def test_the_store_survives_a_corrupt_file(tmp_path):
    """Failing to dictate because a JSON file went bad would be absurd."""
    path = tmp_path / "pending.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert PendingStore(path).load().rows() == []


def test_rows_round_trip_through_the_file(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingStore(path).load()
    store.record("monvi", "Manvi")
    store.save()

    again = PendingStore(path).load().rows()
    assert [(r.mishear, r.correct, r.count) for r in again] == [("monvi", "Manvi", 1)]


def test_an_unreadable_timestamp_is_treated_as_stale():
    assert Pending("a", "b", 1, "not a date").is_expired()


def test_promote_at_is_two():
    # The whole promise: fix it twice, never again.
    assert PROMOTE_AT == 2


# --- which terms reach the decoder ---------------------------------------


def test_hotwords_are_capped_and_ranked_by_use(tmp_path):
    dictionary = DictionaryStore(tmp_path / "dictionary.json").load()
    for i in range(MAX_VOCAB + 10):
        dictionary.add(f"Term{i:02d}")
    # The last few are the ones actually spoken.
    for i in range(MAX_VOCAB + 5, MAX_VOCAB + 10):
        dictionary.note_usage(f"we discussed Term{i:02d} today")

    terms = dictionary.top_terms()
    assert len(terms) == MAX_VOCAB
    for i in range(MAX_VOCAB + 5, MAX_VOCAB + 10):
        assert f"Term{i:02d}" in terms


def test_usage_counts_only_whole_words(tmp_path):
    dictionary = DictionaryStore(tmp_path / "dictionary.json").load()
    dictionary.add("Ann")
    dictionary.note_usage("we announced it")
    assert dictionary.entries()[0].uses == 0
    dictionary.note_usage("Ann said so")
    assert dictionary.entries()[0].uses == 1


def test_uses_survive_a_reload(tmp_path):
    path = tmp_path / "dictionary.json"
    store = DictionaryStore(path).load()
    store.add("ChargeBee")
    store.note_usage("the ChargeBee invoice")
    assert DictionaryStore(path).load().entries()[0].uses == 1
