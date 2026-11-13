"""The screen manager: lazy screens, insets and the update boundary."""

import pytest

from kivy.uix.screenmanager import Screen

from ui.screens.manager import MeloScreenManager


class PaddingScreen(Screen):
    """A screen that records what the manager tells it to pad."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.paddings = []

    def apply_padding(self, top, bottom):
        self.paddings.append((top, bottom))


def make_manager():
    manager = MeloScreenManager()
    built = []

    def factory():
        built.append(True)
        return PaddingScreen()

    manager.register_screen("first", factory)
    manager.register_screen("second", lambda: PaddingScreen())
    return manager, built


# --------------------------------------------------------------------------- #
# Lazy creation                                                               #
# --------------------------------------------------------------------------- #
def test_a_screen_is_built_only_when_it_is_shown():
    manager, built = make_manager()

    assert manager.screens == []
    assert built == []

    manager.current = "first"

    assert built == [True]
    assert manager.has_screen("first")


def test_a_screen_is_not_built_twice():
    manager, built = make_manager()

    manager.current = "first"
    manager.current = "second"
    manager.current = "first"

    assert built == [True]
    assert manager.get_screen("first").paddings is not None


def test_an_unknown_screen_is_a_key_error():
    manager = MeloScreenManager()

    with pytest.raises(KeyError):
        manager.ensure_screen("no-such-screen")


def test_the_update_screen_needs_the_update_check_first():
    manager = MeloScreenManager()

    # Only the update check may open this screen: without a view model the
    # factory fails instead of showing an empty screen.
    with pytest.raises(RuntimeError):
        manager.ensure_screen("update")


# --------------------------------------------------------------------------- #
# Insets                                                                      #
# --------------------------------------------------------------------------- #
def test_the_insets_reach_every_screen():
    manager, _ = make_manager()
    manager.current = "first"
    manager.current = "second"

    manager.inset_top, manager.inset_bottom = 24, 66

    first = manager.get_screen("first")
    second = manager.get_screen("second")
    assert first.paddings[-1] == (24, 66)
    assert second.paddings[-1] == (24, 66)


def test_a_screen_added_later_still_gets_the_insets():
    manager, _ = make_manager()
    manager.inset_top, manager.inset_bottom = 24, 66

    manager.current = "first"

    assert manager.get_screen("first").paddings[-1] == (24, 66)
