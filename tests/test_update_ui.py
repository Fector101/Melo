"""The update screen: the modal, its KV, and the startup boundary."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from kivy.clock import Clock

from models.release import Release, ReleaseAsset
from repositories.update_repository import DownloadCancelled, OWNER
from ui.screens.update_screen import UpdateContent, UpdateScreen
from ui.widgets.update import UpdateChip
from viewmodels.update_view_model import (AVAILABLE, DOWNLOADING, FAILED,
                                          READY, UpdateViewModel)

ROOT = Path(__file__).resolve().parent.parent


def make_release():
    return Release(
        version="0.0.2",
        tag="v0.0.2",
        notes="- Faster scans\n- Gapless playback\n- New update screen",
        body="",
        html_url="https://github.com/Fector101/Melo/releases/tag/v0.0.2",
        published_at="2026-11-01T12:00:00Z",
        asset=ReleaseAsset(
            name="melo-v0.0.2-arm64-v8a.apk",
            size=48000000,
            download_url="https://example.test/x.apk",
            abi="arm64-v8a",
            downloads=12480,
            updated_at="2026-10-01T12:00:00Z",
        ),
    )


class FakeRepository:
    def __init__(self):
        self.labels = []
        self.requested = []
        self.install_calls = []
        self.wait_for_cancel = False
        self.cancelled = False
        self.started = False
        self.installed_version = "0.0.1"
        self.release = make_release()

    def get_installed_version(self):
        return self.installed_version

    def check_for_update(self, installed_version=None, supported_abis=None):
        return self.release

    def get_apk_path(self, filename, directory=None):
        return "/tmp/" + filename

    def apk_is_valid(self, path, expected_size):
        return None

    def do_android_install(self, path):
        self.install_calls.append(path)
        return True

    def download_apk(self, url, filename="melo-update.apk",
                     progress_callback=None, cancel_event=None):
        self.requested.append((url, filename))
        self.started = True
        if self.wait_for_cancel:
            while not cancel_event.is_set():
                time.sleep(0.01)
            self.cancelled = True
            raise DownloadCancelled()
        if progress_callback is not None:
            progress_callback(100)
        return "/tmp/" + filename

    def fetch_contributors(self, limit=8):
        return [OWNER, "bob", "eli"]


def make_screen():
    repository = FakeRepository()
    view_model = UpdateViewModel(repository)
    return UpdateScreen(view_model), view_model, repository


def wait_for_clock(condition, timeout=3.0):
    """Wait for a worker while pumping the Kivy clock on this (main) thread."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        Clock.tick()
        if condition():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------------------- #
# The rendered screen                                                         #
# --------------------------------------------------------------------------- #
def test_the_screen_has_its_content():
    screen, view_model, _ = make_screen()

    assert isinstance(screen.content, UpdateContent)
    # ModalView is an AnchorLayout with no `content` property: the widget only
    # renders when it is actually added to the modal.
    assert screen.content.parent is screen
    assert screen.children == [screen.content]
    assert screen.auto_dismiss is False
    assert wait_for_clock(
        lambda: view_model.contributors == [OWNER, "bob", "eli"])


def test_the_screen_renders_the_release():
    screen, view_model, _ = make_screen()
    assert wait_for_clock(lambda: len(screen.content.ids.avatars.children) == 3)
    Clock.tick()
    content = screen.content
    labels = [widget.text for widget in content.walk()
              if getattr(widget, "text", "")]
    joined = " ".join(labels)

    assert "v0.0.2" in labels
    assert "v0.0.1" in joined
    assert "1 Nov 2026" in joined
    assert "Securely sourced from GitHub." in labels
    assert "Download update" in labels
    assert "Later" in labels
    assert "Fector101/Melo" in joined
    assert "arm64-v8a" in joined
    assert "Faster scans" in joined
    assert content.highlights == ["Faster scans", "Gapless playback",
                                  "New update screen"]
    assert len(content.ids.highlights.children) == 3
    assert content.contributors_text == "@Fector101  ·  @bob  ·  @eli"


def test_the_state_map_drives_the_text():
    screen, view_model, _ = make_screen()
    content = screen.content

    view_model.state = DOWNLOADING
    view_model.progress = 42
    assert content.status_text == "Downloading\u2026  42%"
    assert content.primary_text == "Downloading\u2026"

    view_model.state = READY
    assert content.status_text == "Download complete."
    assert content.primary_text == "Install"

    view_model.state = FAILED
    view_model.failure_text = "Download failed. Check your connection and retry."
    assert content.status_text == view_model.failure_text
    assert content.primary_text == "Retry"

    view_model.state = AVAILABLE
    view_model.failure_text = ""
    assert content.status_text == "Securely sourced from GitHub."
    assert content.primary_text == "Download update"


# --------------------------------------------------------------------------- #
# The buttons                                                                 #
# --------------------------------------------------------------------------- #
def test_the_primary_button_starts_a_download():
    screen, view_model, repository = make_screen()
    content = screen.content

    content.primary_pressed()

    assert wait_for_clock(lambda: repository.requested)
    assert repository.requested[0][1] == "melo-v0.0.2-arm64-v8a.apk"
    assert wait_for_clock(lambda: view_model.state == READY)


def test_the_secondary_button_cancels_a_download():
    screen, view_model, repository = make_screen()
    repository.wait_for_cancel = True
    content = screen.content

    view_model.download()
    assert wait_for_clock(lambda: repository.started)
    assert content.state == DOWNLOADING
    content.secondary_pressed()

    assert wait_for_clock(lambda: view_model.state == AVAILABLE)
    assert repository.cancelled is True


def test_the_later_button_dismisses_the_modal():
    screen, view_model, _ = make_screen()
    dismissed = []
    screen.bind(on_dismiss=lambda *_: dismissed.append(True))
    screen.open(animation=False)

    screen.content.secondary_pressed()

    assert dismissed == [True]


def test_the_chip_is_built_and_tappable():
    screen, view_model, _ = make_screen()
    tapped = []
    chip = UpdateChip(text="Update available  \u00b7  v0.0.2")
    chip.bind(on_release=lambda *_: tapped.append(True))
    Clock.tick()

    assert chip.width > 0
    chip.dispatch("on_release", None)

    assert tapped == [True]


# --------------------------------------------------------------------------- #
# Startup                                                                     #
# --------------------------------------------------------------------------- #
def test_importing_the_app_does_not_import_the_update_ui():
    code = (
        "import sys\n"
        "sys.path.insert(0, 'app_src')\n"
        "import main\n"
        "print('repositories.update_repository' in sys.modules)\n"
        "print('ui.screens.update_screen' in sys.modules)\n"
        "print('ui.widgets.update' in sys.modules)\n"
        "print('viewmodels.update_view_model' in sys.modules)\n"
    )
    environment = dict(os.environ)
    environment.update({
        "KIVY_NO_ARGS": "1",
        "KIVY_NO_CONSOLELOG": "1",
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
    })

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-4:] == [
        "False", "False", "False", "False"]


def test_the_update_kv_is_not_in_the_startup_folder():
    startup_folder = ROOT / "app_src" / "ui" / "kv"
    lazy_folder = startup_folder / "lazy"

    assert (lazy_folder / "update_screen.kv").is_file()
    assert not (startup_folder / "update_screen.kv").exists()
