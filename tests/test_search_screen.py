"""The search screen: filtering, playback and its own window insets."""

import pytest

from kivy.uix.screenmanager import Screen, ScreenManager

from models.track import Track
from repositories.player_repository import PlayerRepository
from ui import load_kv_files
from ui.screens.manager import MeloScreenManager
from ui.screens.search_screen import SearchScreen
from ui.widgets.player import Player
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel
from viewmodels.search_view_model import SearchViewModel


@pytest.fixture(scope="module", autouse=True)
def kv_rules():
    """Widget rules are loaded once; the search rule loads with its module."""
    load_kv_files()


def make_tracks(count=3):
    return [
        Track(path=f"/music/{index}.mp3",
              title=f"Track {index}",
              artist=f"Artist {index}",
              album=f"Album {index}",
              duration_ms=60000)
        for index in range(count)
    ]


@pytest.fixture
def screen(library, artwork, playback, immediate_clock):
    library.tracks = make_tracks()
    library.cached_tracks = library.tracks
    player_repo = PlayerRepository()

    library_vm = LibraryViewModel(
        library_repository=library,
        artwork_repository=artwork,
        player_repo=player_repo,
    )
    library_vm.tracks = library.tracks
    player_vm = PlayerViewModel(
        playback_repository=playback,
        library_view_model=library_vm,
        player_repo=player_repo,
        artwork_repository=artwork,
    )
    search_vm = SearchViewModel(library, artwork, player_repo)
    view = SearchScreen(search_vm, player_vm, library=library_vm)
    # The real screen does this on enter; drive it here so the rows exist.
    view._entrance_work(0)
    return view, library_vm, player_vm


# --------------------------------------------------------------------------- #
# The parts                                                                    #
# --------------------------------------------------------------------------- #
def test_the_search_screen_has_its_parts(screen):
    view, _, _ = screen

    for widget_id in ("main_container", "search_input", "back_button",
                      "clear_button", "result_count", "play_all",
                      "results", "empty_label", "player_slot"):
        assert widget_id in view.ids

    # The app-wide PlayerHost owns the only Player widget.
    assert not any(isinstance(widget, Player)
                   for widget in view.walk(restrict=True))


# --------------------------------------------------------------------------- #
# Filtering                                                                    #
# --------------------------------------------------------------------------- #
def test_an_empty_query_shows_every_track(screen):
    view, _, _ = screen

    assert view.result_count == "3 songs"
    assert view.has_results is True
    assert len(view.ids.results.data) == 3


def test_typing_filters_the_results(screen):
    view, _, _ = screen

    view.ids.search_input.text = "track 1"

    assert view.query == "track 1"
    assert [row["path"] for row in view.ids.results.data] == ["/music/1.mp3"]


def test_the_filter_matches_the_artist(screen):
    view, _, _ = screen

    view.query = "ARTIST 2"
    assert [row["path"] for row in view.ids.results.data] == ["/music/2.mp3"]

    view.query = "artist 0"
    assert [row["path"] for row in view.ids.results.data] == ["/music/0.mp3"]


def test_the_count_uses_the_singular_form(screen):
    view, _, _ = screen

    view.query = "Track 1"

    assert view.result_count == "1 song"


def test_no_matches_shows_the_empty_state(screen):
    view, _, _ = screen

    view.query = "nothing like this"

    assert view.ids.results.data == []
    assert view.has_results is False
    assert view.ids.play_all.disabled is True
    assert view.ids.empty_label.opacity == 1


def test_the_clear_button_restores_every_track(screen):
    view, _, _ = screen

    view.query = "Track 2"
    view.ids.clear_button.dispatch("on_release")

    assert view.query == ""
    assert view.ids.search_input.text == ""
    assert len(view.ids.results.data) == 3


# --------------------------------------------------------------------------- #
# Playback                                                                     #
# --------------------------------------------------------------------------- #
def test_tapping_a_result_plays_that_track(screen, immediate_clock):
    view, library_vm, player_vm = screen

    view.ids.results.data[1]["on_select"]("/music/1.mp3")

    assert player_vm.current_track is library_vm.tracks[1]


def test_play_all_plays_the_first_match(screen, immediate_clock):
    view, library_vm, player_vm = screen

    view.query = "Artist"
    view.ids.play_all.dispatch("on_release")

    assert player_vm.current_track is library_vm.tracks[0]


def test_the_playing_result_is_highlighted(screen, immediate_clock):
    view, library_vm, player_vm = screen

    library_vm.player_repo.current_playlist = library_vm.tracks
    player_vm.play_track(library_vm.tracks[2])

    assert [row["active"] for row in view.ids.results.data] == [
        False, False, True]


def test_cached_artwork_is_used_for_the_rows(screen, artwork):
    view, _, _ = screen

    artwork.art["/music/1.mp3"] = "/cache/1.jpg"
    view.display_found_tracks(view.search_view_model,
                              view.search_view_model.filtered_tracks_value)

    assert view.ids.results.data[1]["art"] == "/cache/1.jpg"
    assert view.ids.results.data[0]["art"] == ""


def test_late_artwork_patches_the_matching_result_row(screen):
    view, library_vm, _ = screen

    library_vm.dispatch("on_artwork_ready", path="/music/1.mp3",
                        art="/cache/1.jpg")

    assert view.ids.results.data[1]["art"] == "/cache/1.jpg"
    assert view.ids.results.data[0]["art"] == ""


# --------------------------------------------------------------------------- #
# Navigation                                                                   #
# --------------------------------------------------------------------------- #
def test_the_back_button_returns_to_the_library(screen):
    view, _, _ = screen
    manager = ScreenManager()
    manager.add_widget(Screen(name="library"))
    view.name = "search"
    manager.add_widget(view)
    manager.current = "search"

    view.ids.back_button.dispatch("on_release")

    assert manager.current == "library"


def test_the_manager_factory_wires_the_search_view_model(screen):
    _, library_vm, player_vm = screen
    fake_manager = type("FakeManager", (), {})()
    fake_manager.library_repository = library_vm._library
    fake_manager.artwork_repository = library_vm._artwork
    fake_manager.player_repo = library_vm.player_repo
    fake_manager.library_view_model = library_vm
    fake_manager.player_view_model = player_vm

    built = MeloScreenManager._MeloScreenManager__create_search_screen(
        fake_manager)

    assert isinstance(built.search_view_model, SearchViewModel)
    assert built.search_view_model.tracks == library_vm.tracks
    assert built.player is player_vm
    assert built.library is library_vm


# --------------------------------------------------------------------------- #
# Insets                                                                       #
# --------------------------------------------------------------------------- #
def test_insets_pad_the_screen_without_losing_horizontal_padding(screen):
    view, _, _ = screen
    container = view.ids.main_container
    left, _, right, _ = container.padding

    view.inset_top = 24
    view.inset_bottom = 16

    assert list(container.padding) == [left, 34, right, 16]


def test_apply_padding_is_safe_for_the_manager_to_call(screen):
    view, _, _ = screen
    container = view.ids.main_container
    left, _, right, _ = container.padding

    view.apply_padding(30, 20)

    assert (view.inset_top, view.inset_bottom) == (30, 20)
    assert list(container.padding) == [left, 40, right, 20]
