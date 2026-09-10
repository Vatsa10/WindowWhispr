"""The recognizer window's geometry, and the modes the app can start in.

The window cannot be hidden -- Chromium freezes an occluded renderer and a
frozen renderer hears nothing, measured -- so how little space it takes and
where it takes it is the whole design. These pin it.
"""

import pytest

from core import autostart
from core.web.pill_host import CORNERS, DEFAULT_CORNER, SIZES, Api, place

SCREEN = (1920, 1080)


def test_the_dot_is_the_smallest_state():
    """It is what the window spends all day being."""
    area = {name: w * h for name, (w, h) in SIZES.items()}
    assert min(area, key=area.get) == "dot"


def test_the_dot_is_small_enough_to_forget():
    width, height = SIZES["dot"]
    assert width <= 24 and height <= 24


def test_every_state_has_a_size():
    for name in ("dot", "live", "arm", "menu"):
        assert SIZES[name][0] > 0 and SIZES[name][1] > 0


@pytest.mark.parametrize("corner", CORNERS)
def test_every_corner_puts_the_window_on_screen(corner):
    for size in SIZES:
        x, y = place(*SCREEN, size=size, corner=corner)
        width, height = SIZES[size]
        assert 0 <= x and x + width <= SCREEN[0]
        assert 0 <= y and y + height <= SCREEN[1]


@pytest.mark.parametrize("corner", CORNERS)
def test_growing_keeps_the_window_anchored_to_its_corner(corner):
    """Otherwise the pill would grow off the edge of the screen it sits on."""
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")

    edges = set()
    for size in SIZES:
        x, y = place(*SCREEN, size=size, corner=corner)
        width, height = SIZES[size]
        edges.add((x + width if right else x, y + height if bottom else y))
    assert len(edges) == 1, "the anchored corner moved between sizes"


def test_the_bottom_margin_clears_the_taskbar():
    _x, y = place(*SCREEN, size="dot", corner="bottom-right")
    assert SCREEN[1] - (y + SIZES["dot"][1]) >= 40


def test_an_unknown_corner_falls_back_rather_than_failing():
    assert place(*SCREEN, corner="middle-of-nowhere") == place(*SCREEN, corner=DEFAULT_CORNER)


def test_a_screen_smaller_than_the_window_still_places_it_on_screen():
    assert place(100, 80, "live") == (0, 0)


# --- the bridge -----------------------------------------------------------


class _FakeWindow:
    def __init__(self):
        self.calls = []

    def resize(self, w, h):
        self.calls.append(("resize", w, h))

    def move(self, x, y):
        self.calls.append(("move", x, y))


def test_resizing_to_the_same_state_does_nothing():
    """set_size is called on every render; only real changes touch the window."""
    window = _FakeWindow()
    api = Api()
    api.bind(window, SCREEN)
    api.set_size("live")
    api.set_size("live")
    assert [c[0] for c in window.calls] == ["resize", "move"]


def test_an_unknown_state_is_ignored():
    window = _FakeWindow()
    api = Api()
    api.bind(window, SCREEN)
    api.set_size("nonsense")
    assert window.calls == []


def test_set_size_without_a_window_is_safe():
    Api().set_size("dot")  # the page can render before the window is bound


def test_changing_corner_moves_without_resizing():
    window = _FakeWindow()
    api = Api()
    api.bind(window, SCREEN, "bottom-right")
    api.set_size("dot")
    window.calls.clear()
    api.set_corner("top-left")
    assert [c[0] for c in window.calls] == ["move"]
    assert window.calls[0][1:] == place(*SCREEN, size="dot", corner="top-left")


def test_an_unknown_corner_is_refused():
    window = _FakeWindow()
    api = Api()
    api.bind(window, SCREEN, "bottom-right")
    api.set_corner("sideways")
    assert window.calls == []


# --- what "start at login" starts ----------------------------------------


def test_autostart_can_point_at_dictation_only():
    assert autostart._command("listen").endswith(" listen")


def test_the_default_autostart_command_starts_the_app():
    assert not autostart._command().endswith(" listen")


def test_the_command_quotes_its_paths():
    """A path with a space breaks an unquoted registry command."""
    for mode in autostart.MODES:
        command = autostart._command(mode)
        assert command.startswith('"')
        assert command.count('"') % 2 == 0
