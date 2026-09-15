"""Which language a segment is decoded as.

The rule that matters: a language nobody declared is never chosen, however
confident the model is. Open-ended detection is what makes English spoken with
an accent come back as the accent's language, and that bug is worse than the
code-switching this exists to support.
"""

from core.asr.decode_policy import DETECT_FLOOR, clamp, resolve


def test_no_secondary_is_a_hard_pin():
    """Anyone who has not opted in must see no change whatsoever."""
    assert clamp({"ru": 0.99}, "en", "") == "en"
    assert clamp({}, "en", "") == "en"


def test_a_confident_secondary_is_chosen():
    assert clamp({"en": 0.2, "hi": 0.9}, "en", "hi") == "hi"


def test_a_confident_primary_is_kept():
    assert clamp({"en": 0.95, "hi": 0.05}, "en", "hi") == "en"


def test_doubt_resolves_to_the_primary():
    """Missing a switch is a clumsy sentence; the wrong language is unreadable."""
    below = DETECT_FLOOR - 0.05
    assert clamp({"en": 0.1, "hi": below}, "en", "hi") == "en"


def test_the_floor_is_the_deciding_line():
    assert clamp({"en": 0.0, "hi": DETECT_FLOOR + 0.01}, "en", "hi") == "hi"
    assert clamp({"en": 0.0, "hi": DETECT_FLOOR - 0.01}, "en", "hi") == "en"


def test_an_undeclared_language_is_never_chosen():
    """The accent bug: Russian-accented English must not become Russian."""
    assert clamp({"ru": 0.99, "en": 0.01}, "en", "hi") == "en"
    assert clamp({"ru": 0.99, "en": 0.01, "hi": 0.0}, "en", "hi") != "ru"


def test_a_secondary_equal_to_the_primary_is_no_pair():
    assert clamp({"en": 0.9}, "en", "en") == "en"


def test_missing_languages_score_zero_rather_than_raising():
    assert clamp({"fr": 0.9}, "en", "hi") == "en"
    assert clamp(None, "en", "hi") == "en"


# --- resolve, around a stand-in model ------------------------------------


class _Model:
    def __init__(self, probabilities=None, explode=False):
        self._probabilities = probabilities or {}
        self._explode = explode
        self.calls = 0

    def detect_language(self, audio=None, **_kwargs):
        self.calls += 1
        if self._explode:
            raise RuntimeError("no features")
        return ("xx", 0.0, list(self._probabilities.items()))


def test_resolve_never_asks_the_model_without_a_pair():
    """Detection costs an encoder pass; a pinned decode must not pay it."""
    model = _Model({"hi": 0.99})
    assert resolve(model, None, "en", "") == "en"
    assert model.calls == 0


def test_resolve_uses_the_detected_language_from_the_pair():
    assert resolve(_Model({"en": 0.1, "hi": 0.92}), None, "en", "hi") == "hi"


def test_a_detection_failure_falls_back_rather_than_raising():
    """A clumsy transcript beats no transcript."""
    assert resolve(_Model(explode=True), None, "en", "hi") == "en"
