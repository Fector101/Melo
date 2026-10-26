"""Test bootstrap.

The app lives in ``app_src`` (that is the directory buildozer ships), so it
is put on the path here. The Android-only parts of the repositories degrade
on their own off Android, which keeps these tests runnable on the desktop.
"""

import sys
import time
from pathlib import Path

import pytest

APP_SRC = Path(__file__).resolve().parent.parent / "app_src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from kivy.clock import Clock  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes                                                                      #
# --------------------------------------------------------------------------- #
class FakePlayback:
    """Stands in for the ``PlaybackRepository``."""

    def __init__(self):
        self.loaded = None
        self.playing = False
        self.position = 0.0
        self.length = 0.0
        self.loop = False
        self.now_playing = None
        self.syncs = 0
        self.released = False
        self.on_track_end = None
        self.on_next = None
        self.on_previous = None
        self.on_playing_state_change = None

    # --- wiring ---
    def set_on_track_end(self, callback):
        self.on_track_end = callback

    def set_on_playing_state_change(self, callback):
        self.on_playing_state_change = callback

    def set_transport_callbacks(self, on_next=None, on_previous=None):
        self.on_next = on_next
        self.on_previous = on_previous

    # --- engine ---
    @property
    def has_controller(self):
        return self.loaded is not None

    @property
    def source(self):
        return self.loaded

    @property
    def state(self):
        return "play" if self.playing else "stop"

    @property
    def is_playing(self):
        return self.playing

    def load(self, path):
        self.loaded = path
        self.position = 0.0
        return True

    def play(self):
        self.playing = True
        self._notify_playing_state()

    def pause(self):
        self.playing = False
        self._notify_playing_state()

    def _notify_playing_state(self):
        if self.on_playing_state_change is not None:
            self.on_playing_state_change(self.playing)

    def seek(self, seconds):
        self.position = float(seconds)

    def get_position(self):
        return self.position

    def get_length(self):
        return self.length

    def set_loop(self, enabled):
        self.loop = bool(enabled)

    def stop(self):
        self.playing = False
        self._notify_playing_state()

    # --- notification ---
    def set_now_playing(self, title, artist):
        self.now_playing = (title, artist)

    def sync_notification(self):
        self.syncs += 1

    def release(self):
        self.released = True


class FakeArtwork:
    """Stands in for the ``ArtworkRepository``."""

    def __init__(self, art=None):
        self.art = dict(art or {})
        self.extracted = []

    def cached(self, track_path):
        return self.art.get(track_path, "")

    def extract(self, track_path):
        self.extracted.append(track_path)
        return self.art.get(track_path, "")


class FakeLibrary:
    """Stands in for the ``LibraryRepository``."""

    def __init__(self, tracks=()):
        self.tracks = list(tracks)
        self.scans = 0

    def scan(self):
        self.scans += 1
        return list(self.tracks)


class FakePermissions:
    """Stands in for the ``PermissionsRepository``."""

    def __init__(self, granted=False, declared=True):
        self.granted = granted
        self.declared = declared
        self.requested = False

    def is_declared_in_manifest(self):
        return self.declared

    def has_audio_access(self):
        return self.granted

    def request_audio_access(self, callback):
        self.requested = True
        callback(self.granted)


# --------------------------------------------------------------------------- #
# Fixtures                                                                   #
# --------------------------------------------------------------------------- #
@pytest.fixture
def immediate_clock(monkeypatch):
    """Run the scheduled callbacks right away instead of on the next frame."""
    monkeypatch.setattr(Clock, "schedule_once",
                        lambda callback, timeout=0: callback(timeout))


@pytest.fixture
def on_android(monkeypatch):
    """Pretend that the app runs on Android."""
    monkeypatch.setattr("viewmodels.library_view_model.on_android_platform",
                        lambda: True)


@pytest.fixture
def playback():
    return FakePlayback()


@pytest.fixture
def artwork():
    return FakeArtwork()


@pytest.fixture
def library():
    return FakeLibrary()


@pytest.fixture
def permissions():
    return FakePermissions()


def wait_for(condition, timeout=3.0):
    """Wait until ``condition()`` is true (the workers are real threads)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False
