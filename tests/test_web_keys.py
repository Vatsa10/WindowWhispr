"""Which keys can be the talk key.

A talk key the hook cannot match does not raise anything: dictation simply
never starts again. So the rules about what may be bound live in one place,
are enforced on the way in, and are pinned here.
"""

from core.web.app_api import AppApi, _validated
from core.web.keys import (
    DEFAULT_TALK_KEY,
    FORBIDDEN,
    SUGGESTED_TALK_KEYS,
    describe,
    is_usable,
    normalize,
)


def test_the_default_is_right_ctrl():
    assert DEFAULT_TALK_KEY == "right ctrl"


def test_the_suggestions_are_keys_nothing_else_claims():
    """Every offered key must be safe to hold down for a whole sentence."""
    for value, label in SUGGESTED_TALK_KEYS:
        assert is_usable(value), f"{value} is offered but not usable"
        assert label.strip()


def test_laptops_without_a_right_ctrl_have_somewhere_to_go():
    # The whole reason the key is rebindable: compact layouts drop Right Ctrl.
    offered = {value for value, _ in SUGGESTED_TALK_KEYS}
    assert {"right alt", "caps lock"} <= offered


def test_typing_keys_are_refused():
    """Binding the talk key to Space means Space stops working everywhere."""
    for name in ("space", "enter", "backspace", "tab", "a", "z", "1"):
        assert is_usable(name) is False


def test_the_plain_modifiers_are_refused():
    # Left Ctrl reports the same name as the Ctrl in every copy and paste.
    for name in ("ctrl", "left ctrl", "shift", "alt", "windows"):
        assert is_usable(name) is False
        assert name in FORBIDDEN or name.startswith("left")


def test_arrow_keys_are_refused():
    for name in ("up", "down", "left", "right"):
        assert is_usable(name) is False


def test_an_unusable_key_normalizes_to_the_default():
    assert normalize("space") == DEFAULT_TALK_KEY
    assert normalize("") == DEFAULT_TALK_KEY
    assert normalize(None) == DEFAULT_TALK_KEY


def test_a_usable_key_survives_normalization():
    assert normalize("Caps Lock") == "caps lock"
    assert normalize("  F13 ") == "f13"


def test_describe_falls_back_to_the_key_itself():
    assert describe("right ctrl") == "Right Ctrl"
    assert describe("kana") == "Kana"


# --- the settings route enforces the same rules --------------------------


def test_an_unusable_talk_key_never_reaches_the_config():
    assert _validated({"ptt_key": "space"}) == {}
    assert _validated({"ptt_key": "caps lock"}) == {"ptt_key": "caps lock"}


def test_an_unknown_pill_corner_is_dropped():
    assert _validated({"pill_corner": "sideways"}) == {}
    assert _validated({"pill_corner": "top-left"}) == {"pill_corner": "top-left"}


def test_saving_only_an_unusable_key_changes_nothing():
    """It must not report success for a change it refused."""
    saved = AppApi().save_config({"ptt_key": "enter"})
    assert saved["saved"] is False


def test_the_page_is_told_which_keys_to_suggest():
    choices = AppApi().choices()
    assert [k["value"] for k in choices["keys"]][0] == DEFAULT_TALK_KEY
    assert all(k["label"] for k in choices["keys"])
