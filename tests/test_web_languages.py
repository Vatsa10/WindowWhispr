"""The dictation language list.

A tag that reaches the recognizer wrong means the user speaks and nothing
sensible comes back, with no error to explain it. So normalization is
forgiving about how the setting was written and strict about what it emits.
"""

from core.web.languages import AUTO, LANGUAGES, TAGS, display_name, normalize


def test_the_first_entry_is_automatic():
    # It is the default, and a dropdown that opens on it says so.
    assert LANGUAGES[0][0] == AUTO


def test_every_entry_is_unique_and_named():
    tags = [tag for tag, _ in LANGUAGES]
    assert len(tags) == len(set(tags))
    assert all(name.strip() for _, name in LANGUAGES)


def test_tags_are_bcp47_apart_from_automatic():
    for tag, _ in LANGUAGES:
        assert tag == AUTO or ("-" in tag and tag.split("-")[1].isupper())


def test_a_stored_setting_survives_case_and_underscores():
    # Config files get hand-edited, and older releases wrote other spellings.
    assert normalize("HI_in") == "hi-IN"
    assert normalize("en-us") == "en-US"


def test_a_bare_language_finds_a_region():
    """"en" should dictate in English, not fall back to the system language."""
    assert normalize("en") == "en-US"
    assert normalize("de") == "de-DE"


def test_anything_unrecognized_follows_the_system():
    for value in ("", "  ", "klingon", "zz-ZZ", None):
        assert normalize(value) == AUTO


def test_normalize_is_idempotent():
    for tag in TAGS:
        assert normalize(normalize(tag)) == normalize(tag)


def test_display_name_falls_back_to_the_tag():
    assert display_name("hi-IN") == "Hindi"
    assert display_name("xx-XX") == "xx-XX"
