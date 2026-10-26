"""The repositories: the boundary to the device."""

import os

from models.track import Track
from repositories.artwork_repository import ArtworkRepository
from repositories.library_repository import LibraryRepository
from repositories.permissions_repository import PermissionsRepository
from repositories.playback_repository import PlaybackRepository
from ui.format import format_duration


# --------------------------------------------------------------------------- #
# The model                                                                   #
# --------------------------------------------------------------------------- #
def test_a_track_falls_back_to_its_file_name():
    track = Track(path="/music/01 - Song.mp3")

    assert track.display_title == "01 - Song.mp3"
    assert track.display_artist == "Unknown Artist"
    assert track.duration_seconds == 0.0


def test_a_track_knows_its_length():
    track = Track(path="/music/song.mp3", title="Song", artist="Band",
                  duration_ms=125000)

    assert track.duration_seconds == 125.0
    assert track.display_title == "Song"
    assert track.display_artist == "Band"


def test_a_duration_is_formatted_for_the_list():
    assert format_duration(0) == "0:00"
    assert format_duration(9) == "0:09"
    assert format_duration(125) == "2:05"


# --------------------------------------------------------------------------- #
# The library                                                                 #
# --------------------------------------------------------------------------- #
def test_scanning_off_android_finds_nothing():
    assert LibraryRepository().scan() == []


# --------------------------------------------------------------------------- #
# The artwork                                                                 #
# --------------------------------------------------------------------------- #
def test_the_artwork_cache_answers_without_io(tmp_path):
    repository = ArtworkRepository(str(tmp_path))

    assert repository.cached("/music/song.mp3") == ""
    assert repository._cache_dir == os.path.join(str(tmp_path), "art_cache")


def test_the_artwork_is_not_extracted_off_android(tmp_path):
    repository = ArtworkRepository(str(tmp_path))

    # No MediaMetadataRetriever off Android, so there is nothing to decode.
    assert repository.extract("/music/song.mp3") == ""
    assert repository.cached("/music/song.mp3") == ""


# --------------------------------------------------------------------------- #
# The permissions                                                             #
# --------------------------------------------------------------------------- #
def test_a_missing_manifest_check_is_not_fatal():
    # The check itself is optional; the app must not crash without it.
    assert PermissionsRepository().is_declared_in_manifest() in (True, False)


# --------------------------------------------------------------------------- #
# The playback                                                                #
# --------------------------------------------------------------------------- #
def test_an_empty_playback_repository():
    repository = PlaybackRepository()

    assert repository.has_controller is False
    assert repository.source is None
    assert repository.state == "stop"
    assert repository.is_playing is False
    assert repository.get_position() == 0.0
    assert repository.get_length() == 0.0


def test_the_loop_flag_reaches_the_engine():
    repository = PlaybackRepository()

    repository.set_loop(True)

    assert repository.loop_enabled is True


def test_loading_a_missing_file_does_not_crash():
    repository = PlaybackRepository()

    # Kivy's sound loader hands out a sound object even for a file it cannot
    # open, so this only checks that nothing blows up.
    repository.load("/does/not/exist.mp3")

    repository.release()


def test_releasing_is_safe_without_a_track():
    repository = PlaybackRepository()

    repository.release()  # must not raise
