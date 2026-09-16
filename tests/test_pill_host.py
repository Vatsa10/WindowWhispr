"""The recognizer window's geometry, and the modes the app can start in.

The window cannot be hidden -- Chromium freezes an occluded renderer and a
frozen renderer hears nothing, measured -- so how little space it takes and
where it takes it is the whole design. These pin it.
"""

import pytest

from core import autostart
from core.web.pill_host import CORNERS, DEFAULT_CORNER, SIZES, Api, place, scaled

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


class _FakeEdge:
    """The window layer, recorded rather than performed.

    The real one moves an Edge window around with Win32 calls; what these tests
    care about is which calls are made and with what.
    """

    def __init__(self, scale=1.0):
        self.calls = []
        self.scale = scale

    def dpi_scale(self, _hwnd):
        return self.scale

    def place(self, _hwnd, x, y, width, height, scale=1.0):
        self.calls.append(("place", x, y, width, height, scale))


@pytest.fixture
def fake_edge(monkeypatch):
    stub = _FakeEdge()
    monkeypatch.setattr("core.web.pill_host.edge", stub)
    return stub


def _api(fake, corner=DEFAULT_CORNER):
    api = Api()
    api.bind(1234, None, SCREEN, corner)
    return api


def test_resizing_to_the_same_state_does_nothing(fake_edge):
    """set_size is called on every render; only real changes touch the window."""
    api = _api(fake_edge)
    api.set_size("live")
    api.set_size("live")
    assert len(fake_edge.calls) == 1


def test_an_unknown_state_is_ignored(fake_edge):
    api = _api(fake_edge)
    api.set_size("nonsense")
    assert fake_edge.calls == []


def test_set_size_without_a_window_is_safe():
    Api().set_size("dot")  # the page can render before the window is bound


def test_changing_corner_moves_to_the_new_corner(fake_edge):
    api = _api(fake_edge, "bottom-right")
    api.set_size("dot")
    fake_edge.calls.clear()
    api.set_corner("top-left")
    _call, x, y, _w, _h, _scale = fake_edge.calls[0]
    assert (x, y) == place(*SCREEN, size="dot", corner="top-left")


def test_an_unknown_corner_is_refused(fake_edge):
    api = _api(fake_edge, "bottom-right")
    api.set_corner("sideways")
    assert fake_edge.calls == []


# --- scaled displays ------------------------------------------------------


def test_the_window_is_sized_in_physical_pixels(monkeypatch):
    """A 340px pill on a 150% screen needs a 510px window.

    Asking for 340 gets a window too small for its own contents, which is what
    the pill looked like when it first moved into an Edge window: the right
    thing drawn inside scrollbars.
    """
    stub = _FakeEdge(scale=1.5)
    monkeypatch.setattr("core.web.pill_host.edge", stub)
    api = Api()
    api.bind(1234, None, SCREEN, "bottom-right")
    api.set_size("live")
    _call, _x, _y, width, height, scale = stub.calls[0]
    assert (width, height) == (SIZES["live"][0] * 1.5, SIZES["live"][1] * 1.5)
    # The window layer needs the scale too: Chromium's own title bar is hidden
    # by making the window taller by a scaled amount and clipping it off.
    assert scale == 1.5


def test_scaling_leaves_an_unscaled_display_alone():
    assert scaled("live") == SIZES["live"]


@pytest.mark.parametrize("corner", CORNERS)
def test_a_scaled_window_still_lands_on_screen(corner):
    for size in SIZES:
        x, y = place(*SCREEN, size=size, corner=corner, scale=1.5)
        width, height = scaled(size, 1.5)
        assert 0 <= x and x + width <= SCREEN[0]
        assert 0 <= y and y + height <= SCREEN[1]
