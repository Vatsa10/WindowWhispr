"""The recognizer window's geometry and the modes it can start in.

The window cannot be hidden -- Chromium freezes an occluded renderer and a
frozen renderer hears nothing -- so how little space it takes is the whole
design, and these pin it.
"""

from core import autostart
from core.web.pill_host import SIZES, Api, place


def test_idle_is_the_smallest_state():
    """Idle is what it spends all day at, so it must be the small one."""
    area = {name: w * h for name, (w, h) in SIZES.items()}
    assert min(area, key=area.get) == "idle"


def test_idle_is_small_enough_to_ignore():
    width, height = SIZES["idle"]
    assert width <= 160 and height <= 36


def test_every_state_has_a_size():
    for name in ("idle", "live", "arm", "menu"):
        assert SIZES[name][0] > 0 and SIZES[name][1] > 0


def test_the_pill_sits_bottom_centre():
    x, y = place(1920, 1080, "live")
    width, height = SIZES["live"]
    assert x + width // 2 == 1920 // 2 or abs((x + width // 2) - 960) <= 1
    assert y + height < 1080  # clear of the bottom edge


def test_growing_keeps_the_pill_centred():
    """Otherwise it slides sideways every time it has something to say."""
    centres = {
        name: place(1920, 1080, name)[0] + SIZES[name][0] // 2
        for name in SIZES
    }
    assert len(set(centres.values())) == 1


def test_a_screen_smaller_than_the_pill_still_places_it_on_screen():
    assert place(100, 80, "live") == (0, 0)


def test_resizing_to_the_same_state_does_nothing():
    """set_size is called on every render; only real changes touch the window."""
    calls = []

    class FakeWindow:
        resize = staticmethod(lambda w, h: calls.append(("resize", w, h)))
        move = staticmethod(lambda x, y: calls.append(("move", x, y)))

    api = Api()
    api.window = FakeWindow()
    api.set_size("live")
    api.set_size("live")
    assert [c[0] for c in calls] == ["resize", "move"]


def test_an_unknown_state_is_ignored():
    class Boom:
        def resize(self, *_):
            raise AssertionError("should not resize")

        def move(self, *_):
            raise AssertionError("should not move")

    api = Api()
    api.window = Boom()
    api.set_size("nonsense")


def test_set_size_without_a_window_is_safe():
    Api().set_size("idle")  # the page can render before the window is bound


# --- what "start at login" starts ----------------------------------------


def test_autostart_can_point_at_browser_dictation():
    assert autostart._command("listen").endswith(" listen")


def test_the_default_autostart_command_starts_the_app():
    assert not autostart._command().endswith(" listen")


def test_the_command_quotes_its_paths():
    """A path such as C: Program Files breaks an unquoted registry command."""
    for mode in autostart.MODES:
        command = autostart._command(mode)
        assert command.startswith('"')
        assert command.count('"') % 2 == 0
