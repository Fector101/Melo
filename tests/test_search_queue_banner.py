"""The library header banner that returns to a search queue."""

import pytest

from kivy.clock import Clock
from kivy.metrics import dp

from repositories.player_repository import PlayerRepository
from ui import load_kv_files
from ui.screens.library_screen import LibraryScreen
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel


@pytest.fixture(scope="module", autouse=True)
def kv_rules():
    load_kv_files()


@pytest.fixture
def view(library, artwork, playback, immediate_clock):
    player_repo = PlayerRepository()
    library_vm = LibraryViewModel(library, artwork, player_repo)
    player_vm = PlayerViewModel(playback, library_vm, player_repo, artwork)
    return LibraryScreen(library_vm, player_vm), player_vm


class FakeManager:
    def __init__(self):
        self.opened = []

    def open_search(self, query):
        self.opened.append(query)


def test_the_banner_is_hidden_for_library_playback(view):
    screen, _ = view
    banner = screen.ids.search_banner

    assert screen.search_query == ""
    assert banner.opacity == 0
    assert banner.disabled is True
    assert banner.height == 0
    assert screen.ids.status.opacity == 1
    assert screen.ids.status.height == dp(34)


def test_the_banner_shows_the_queue_query(view):
    screen, player_vm = view

    player_vm.playlist_query = "khruangbin"

    assert screen.search_query == "khruangbin"
    banner = screen.ids.search_banner
    assert banner.opacity == 1
    assert banner.disabled is False
    assert banner.height == dp(34)
    assert banner.text == "Search: “khruangbin”"
    assert screen.ids.status.opacity == 0
    assert screen.ids.status.height == 0


def test_tapping_the_banner_reopens_the_query(view):
    screen, player_vm = view
    player_vm.playlist_query = "khruangbin"
    manager = FakeManager()
    screen.manager = manager

    screen.ids.search_banner.dispatch("on_release")

    assert manager.opened == ["khruangbin"]


def test_status_stays_in_the_header(view):
    screen, _ = view
    screen.size = (390, 740)
    Clock.tick()
    Clock.tick()

    assert screen.ids.status.center_y > screen.height / 2
