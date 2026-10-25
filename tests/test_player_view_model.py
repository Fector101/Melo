"""The player view model: the transport commands and the progress ticker."""

import pytest
from kivy.clock import Clock

from models.track import Track
from viewmodels.player_view_model import PlayerViewModel


def make_tracks(count=3):
    return [Track(path=f"/music/{index}.mp3", title=f"Track {index}",
                  artist=f"Artist {index}", duration_ms=60000 * (index + 1))
            for index in range(count)]


@pytest.fixture
def tracks(library):
    library.tracks = make_tracks()
    return library.tracks


@pytest.fixture
def player(playback, library, artwork, tracks):
    from viewmodels.library_view_model import LibraryViewModel

    library_vm = LibraryViewModel(library, artwork, None)
    library_vm.tracks = tracks  # the playlist the player works on
    return PlayerViewModel(playback, library_vm, artwork)


# --------------------------------------------------------------------------- #
# Commands                                                                    #
# --------------------------------------------------------------------------- #
def test_playing_a_track_loads_it(player, playback, tracks):
    player.play_track(tracks[1])

    assert playback.loaded == "/music/1.mp3"
    assert playback.playing is True
    assert player.title == "Track 1"
    assert player.artist == "Artist 1"
    assert player.current_track is tracks[1]


def test_playing_a_track_publishes_it_in_the_notification(player, playback,
                                                          tracks):
    player.play_track(tracks[2])

    assert playback.now_playing == ("Track 2", "Artist 2")


def test_toggle_play_pause_pauses_and_resumes(player, playback, tracks):
    player.play_track(tracks[0])
    assert playback.playing is True

    player.toggle_play_pause()
    assert playback.playing is False
    assert player.is_playing is False

    player.toggle_play_pause()
    assert playback.playing is True
    assert player.is_playing is True


def test_toggle_play_pause_without_a_track_plays_the_first_one(player,
                                                                playback,
                                                                tracks):
    player.toggle_play_pause()

    assert playback.loaded == "/music/0.mp3"
    assert playback.playing is True


def test_next_and_previous_track(player, playback, tracks):
    player.play_track(tracks[0])

    player.next_track()
    assert playback.loaded == "/music/1.mp3"

    player.previous_track()
    assert playback.loaded == "/music/0.mp3"


def test_notification_next_and_previous_play_audio_before_ui_refresh(
        player, playback, tracks, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        Clock, "schedule_once",
        lambda callback, timeout=0: scheduled.append((callback, timeout)))
    player.play_track(tracks[0])

    playback.on_next()

    assert playback.loaded == "/music/1.mp3"
    assert player.current_track is tracks[0]
    assert len(scheduled) == 1
    callback, timeout = scheduled.pop()
    assert timeout == 0
    callback(0)
    assert playback.loaded == "/music/1.mp3"
    assert player.current_track is tracks[1]

    playback.on_previous()

    assert playback.loaded == "/music/0.mp3"
    assert player.current_track is tracks[1]
    assert len(scheduled) == 1
    callback, timeout = scheduled.pop()
    assert timeout == 0
    callback(0)
    assert playback.loaded == "/music/0.mp3"
    assert player.current_track is tracks[0]


def test_notification_previous_restarts_audio_before_ui_refresh(
        player, playback, tracks, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        Clock, "schedule_once",
        lambda callback, timeout=0: scheduled.append(callback))
    player.play_track(tracks[1])
    playback.position = 10.0
    player.position = 10.0

    playback.on_previous()

    assert playback.loaded == "/music/1.mp3"
    assert playback.position == 0.0
    assert player.position == 10.0
    assert len(scheduled) == 1
    scheduled.pop()(0)
    assert player.position == 0.0


def test_previous_restarts_the_track_after_three_seconds(player, playback,
                                                         tracks):
    player.play_track(tracks[1])
    playback.position = 10.0

    player.previous_track()

    assert playback.loaded == "/music/1.mp3"  # not the previous one
    assert playback.position == 0.0


def test_seek_moves_the_position(player, playback, tracks, immediate_clock):
    player.play_track(tracks[0])

    player.seek(42.0)

    assert playback.position == 42.0
    assert player.position == 42.0


def test_toggle_loop(player, playback, tracks):
    player.play_track(tracks[0])

    player.toggle_loop()

    assert player.loop_enabled is True
    assert playback.loop is True


# --------------------------------------------------------------------------- #
# The ticker                                                                  #
# --------------------------------------------------------------------------- #
def test_the_ticker_follows_the_position(player, playback, tracks):
    player.play_track(tracks[0])
    playback.length = 60.0
    playback.position = 12.0

    player._on_tick(0.25)

    assert player.position == 12.0
    assert player.duration == 60.0
    assert player.is_playing is True


def test_the_ticker_keeps_quiet_while_the_user_drags(player, playback,
                                                     tracks):
    player.play_track(tracks[0])
    playback.length = 60.0
    playback.position = 30.0
    player.set_seeking(True)

    player._on_tick(0.25)

    assert player.position == 0.0  # not moved by the ticker


def test_the_ticker_advances_at_the_end_of_a_track(player, playback, tracks):
    player.play_track(tracks[0])
    playback.length = 60.0
    playback.position = 59.9

    player._on_tick(0.25)

    assert playback.loaded == "/music/1.mp3"
    assert playback.playing is True


def test_the_native_end_callback_advances(player, playback, tracks):
    player.play_track(tracks[0])

    playback.on_track_end()

    assert playback.loaded == "/music/1.mp3"


def test_the_native_end_callback_does_not_advance_when_looping(player,
                                                                playback,
                                                                tracks):
    player.play_track(tracks[0])
    player.toggle_loop()

    playback.on_track_end()

    assert playback.loaded == "/music/0.mp3"


def test_the_end_of_the_playlist_stops_the_playback(player, playback, tracks):
    player.play_track(tracks[-1])

    playback.on_track_end()

    assert playback.playing is False
    assert player.is_playing is False
    assert player.position == 0.0


def test_the_status_line_shows_the_current_track(player, tracks):
    player.play_track(tracks[1])

    assert player._library_viewmodel.status_text == "Track 2 / 3"
