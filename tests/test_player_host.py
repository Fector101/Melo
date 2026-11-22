"""The app-wide player bar: one widget and one set of bindings."""

import pytest

from kivy.event import EventDispatcher
from kivy.properties import NumericProperty, ObjectProperty
from kivy.uix.screenmanager import Screen

from models.track import Track
from repositories.player_repository import PlayerRepository
from ui import load_kv_files
from ui.widgets.player import Player
from ui.widgets.player_host import PLAYER_HEIGHT, PlayerHost
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel


@pytest.fixture(scope="module", autouse=True)
def kv_rules():
    """Widget KV rules are loaded once for the whole module."""
    load_kv_files()


class FakeManager(EventDispatcher):
    """Only the bit of ScreenManager the host needs."""

    current_screen = ObjectProperty(None, allownone=True)


class InsetScreen(Screen):
    """A screen with the inset property the host follows."""

    inset_bottom = NumericProperty(0)


@pytest.fixture
def host(playback, artwork, library):
    player_repo = PlayerRepository()
    library_vm = LibraryViewModel(library, artwork, player_repo)
    library_vm.tracks = [
        Track(path=f"/music/{index}.mp3", title=f"Track {index}",
              artist="Artist", duration_ms=60000)
        for index in range(3)
    ]
    player_repo.current_playlist = library_vm.tracks
    player_vm = PlayerViewModel(playback, library_vm, player_repo, artwork)
    manager = FakeManager()
    return PlayerHost(player_vm, manager=manager), player_vm, manager, library_vm


def players(widget):
    """Every Player widget under ``widget`` (there had better be one)."""
    return [child for child in widget.walk(restrict=True)
            if isinstance(child, Player)]


# --------------------------------------------------------------------------- #
# One widget                                                                   #
# --------------------------------------------------------------------------- #
def test_the_host_owns_exactly_one_player(host):
    view, _, _, _ = host

    assert players(view) == [view.player]
    assert len(players(view)) == 1

    screen = InsetScreen(name="search")
    update = InsetScreen(name="update")

    for current in (screen, update, screen):
        view.manager.current_screen = current
        assert players(view) == [view.player]


# --------------------------------------------------------------------------- #
# View model -> widget                                                         #
# --------------------------------------------------------------------------- #
def test_the_bar_shows_the_view_model_state(host):
    view, player_vm, _, _ = host
    bar = view.player

    player_vm.title = "A title"
    player_vm.artist = "An artist"
    player_vm.art = "/cache/a.jpg"
    player_vm.duration = 123.0
    player_vm.loop_enabled = True
    player_vm.is_playing = True
    player_vm.position = 42.0

    assert bar.title == "A title"
    assert bar.artist == "An artist"
    assert bar.art == "/cache/a.jpg"
    assert bar.total == 123.0
    assert bar.loop_on is True
    assert bar.playing is True
    assert bar.position == 42.0


# --------------------------------------------------------------------------- #
# Widget -> view model                                                         #
# --------------------------------------------------------------------------- #
def test_transport_buttons_drive_the_view_model(host, immediate_clock):
    view, player_vm, _, library_vm = host
    view.manager.current_screen = InsetScreen(name="library")
    bar = view.player

    player_vm.play_track(library_vm.tracks[0])
    bar.ids.next_button.dispatch("on_release")
    assert player_vm.current_track is library_vm.tracks[1]

    bar.ids.play_button.dispatch("on_release")
    assert player_vm.is_playing is False

    bar.ids.repeat_button.dispatch("on_release")
    assert player_vm.loop_enabled is True


def test_seek_requests_drive_the_view_model(host, playback, immediate_clock):
    view, player_vm, _, library_vm = host
    seek = view.player.ids.seek
    player_vm.play_track(library_vm.tracks[0])

    seek.on_seek_requested(12.0)
    assert playback.position == 12.0

    seek.seeking = True
    assert player_vm.is_seeking is True

    seek.seeking = False
    assert player_vm.is_seeking is False


# --------------------------------------------------------------------------- #
# Visibility / insets                                                          #
# --------------------------------------------------------------------------- #
def test_the_bar_follows_the_current_screen(host):
    view, _, manager, _ = host
    bar = view.player
    library = InsetScreen(name="library")
    library.inset_bottom = 24
    search = InsetScreen(name="search")
    search.inset_bottom = 16
    update = InsetScreen(name="update")

    manager.current_screen = library
    assert view.visible is True
    assert view.inset_bottom == 24
    assert bar.y == 24

    manager.current_screen = search
    assert view.visible is True
    assert view.inset_bottom == 16
    assert bar.y == 16

    manager.current_screen = update
    assert view.visible is False
    assert bar.y == -PLAYER_HEIGHT

    manager.current_screen = library
    assert view.visible is True
    assert view.inset_bottom == 24
    assert bar.y == 24
