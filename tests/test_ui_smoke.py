"""The screen: the wiring between the view models and the widgets."""

import pytest

from kivy.clock import Clock
from kivy.metrics import dp

from models.track import Track
from ui import load_kv_files
from ui.screens.library_screen import LibraryScreen
from ui.widgets.player import Player
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel


@pytest.fixture(scope="module", autouse=True)
def kv_rules():
    """The KV rules of the UI layer (loaded once for the whole module)."""
    load_kv_files()


@pytest.fixture
def screen(playback, artwork, library, permissions):
    library_vm = LibraryViewModel(library, artwork, permissions)
    player_vm = PlayerViewModel(playback, library_vm, artwork)
    return LibraryScreen(library_vm, player_vm), library_vm, player_vm


def make_tracks(count=3):
    return [Track(path=f"/music/{index}.mp3", title=f"Track {index}",
                  artist=f"Artist {index}", duration_ms=60000)
            for index in range(count)]


# --------------------------------------------------------------------------- #
# The parts                                                                   #
# --------------------------------------------------------------------------- #
def test_the_screen_has_its_parts(screen):
    view, _, _ = screen

    assert "songs" in view.ids
    assert "player_bar" in view.ids
    assert "fab" in view.ids
    assert "prev_button" in view.ids.player_bar.ids
    assert "play_button" in view.ids.player_bar.ids
    assert "next_button" in view.ids.player_bar.ids
    assert "repeat_button" in view.ids.player_bar.ids
    assert "seek" in view.ids.player_bar.ids


# --------------------------------------------------------------------------- #
# The list                                                                    #
# --------------------------------------------------------------------------- #
def test_the_rows_are_built_from_the_tracks(screen):
    view, library_vm, _ = screen
    library_vm.tracks = make_tracks()

    rows = view.ids.songs.data

    assert len(rows) == 3
    assert rows[0]["title"] == "Track 0"
    assert rows[0]["artist"] == "Artist 0"
    assert rows[0]["duration"] == "1:00"
    assert rows[0]["path"] == "/music/0.mp3"
    assert rows[0]["active"] is False


def test_the_row_of_the_playing_track_is_highlighted(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()

    player_vm.play_track(library_vm.tracks[1])

    assert view.ids.songs.data[1]["active"] is True
    assert view.ids.songs.data[0]["active"] is False


def test_tapping_a_row_plays_the_track(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()

    view.ids.songs.data[2]["on_select"]("/music/2.mp3")

    assert player_vm.current_track is library_vm.tracks[2]


def test_a_row_keeps_its_callback_when_it_is_recycled():
    from ui.widgets.song_row import SongRow

    row = SongRow()
    tapped = []
    row.refresh_view_attrs(None, 0, {"title": "Song", "path": "/music/0.mp3",
                                     "on_select": tapped.append})

    assert row.title == "Song"
    assert row.path == "/music/0.mp3"

    row.on_release(None)

    assert tapped == ["/music/0.mp3"]


def test_the_cover_of_a_track_fills_its_row(screen):
    view, library_vm, _ = screen
    library_vm.tracks = make_tracks()

    library_vm.dispatch("on_artwork_ready", path="/music/1.mp3",
                        art="/cache/1.jpg")

    assert view.ids.songs.data[1]["art"] == "/cache/1.jpg"
    assert view.ids.songs.data[0]["art"] == ""


# --------------------------------------------------------------------------- #
# The player                                                                  #
# --------------------------------------------------------------------------- #
def test_the_player_bar_shows_what_the_player_reports(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()

    player_vm.play_track(library_vm.tracks[0])

    player_bar = view.ids.player_bar
    assert player_bar.title == "Track 0"
    assert player_bar.artist == "Artist 0"
    assert player_bar.playing is True
    assert player_bar.total == 60.0


def test_the_position_moves_the_seek_bar(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()
    player_vm.play_track(library_vm.tracks[0])

    player_vm.position = 12.0

    assert view.ids.player_bar.position == 12.0


def test_the_next_button_plays_the_next_track(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()
    player_vm.play_track(library_vm.tracks[0])

    view.ids.player_bar.ids.next_button.dispatch("on_release", None)

    assert player_vm.current_track is library_vm.tracks[1]


def test_the_play_button_pauses_the_playback(screen):
    view, library_vm, player_vm = screen
    library_vm.tracks = make_tracks()
    player_vm.play_track(library_vm.tracks[0])

    view.ids.player_bar.ids.play_button.dispatch("on_release", None)

    assert player_vm.is_playing is False


def test_the_repeat_button_switches_the_loop(screen):
    view, _, player_vm = screen

    view.ids.player_bar.ids.repeat_button.dispatch("on_release", None)

    assert player_vm.loop_enabled is True


def test_the_transport_buttons_have_a_tap_area_bigger_than_their_glyphs():
    """The glyphs keep their size; the widget around them is the touch target."""
    bar = Player(size=(dp(360), dp(175)), pos=(0, 0))
    for _ in range(3):  # let the nested layouts run
        Clock.tick()

    glyphs = {"prev_button": (dp(16), dp(16)),
              "play_button": (dp(16), dp(20)),
              "next_button": (dp(16), dp(16)),
              "repeat_button": (dp(25), dp(25))}
    for name, glyph_size in glyphs.items():
        button = bar.ids[name]
        assert tuple(button.glyph_size) == glyph_size
        assert button.width == dp(44) and button.height == dp(44)
        assert button.width > glyph_size[0]
        assert button.height > glyph_size[1]

    prev, play, next_ = (bar.ids[name]
                         for name in ("prev_button", "play_button",
                                      "next_button"))
    assert prev.right <= play.x      # the targets sit next to each other
    assert play.right <= next_.x     # without overlapping
    assert prev.glyph_box()[0] == prev.x + (dp(44) - dp(16)) / 2.


def test_the_scan_button_starts_a_scan(screen):
    view, library_vm, _ = screen
    calls = []
    library_vm.scan = lambda: calls.append(True)

    view.ids.fab.dispatch("on_release", None)

    assert calls == [True]


def test_the_status_line_is_shown(screen):
    view, library_vm, _ = screen

    library_vm.set_status("3 songs added")

    assert view.status_text == "3 songs added"
