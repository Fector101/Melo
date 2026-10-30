"""The update view model: the download/install state machine."""

import threading
import time

from models.release import Release, ReleaseAsset
from repositories.update_repository import DownloadCancelled, OWNER
from viewmodels.update_view_model import (AVAILABLE, DOWNLOADING, FAILED,
                                          INSTALLING, READY, UpdateViewModel,
                                          _format_date, _format_size, _with_v)


def make_release():
    return Release(
        version="0.0.2",
        tag="v0.0.2",
        notes="- Faster scans\n- Gapless playback",
        body="",
        html_url="https://github.com/Fector101/Melo/releases/tag/v0.0.2",
        published_at="2026-11-01T12:00:00Z",
        asset=ReleaseAsset(
            name="melo-v0.0.2-arm64-v8a.apk",
            size=48000000,
            download_url="https://example.test/melo-v0.0.2-arm64-v8a.apk",
            abi="arm64-v8a",
            downloads=12480,
            updated_at="2026-10-01T12:00:00Z",
        ),
    )


class FakeRepository:
    def __init__(self):
        self.requested = []
        self.install_calls = []
        self.started = threading.Event()
        self.cancelled = False
        self.existing = None
        self.result = "/tmp/melo-v0.0.2-arm64-v8a.apk"
        self.error = None
        self.install_result = True
        self.contributors = [OWNER, "bob"]
        self.wait_for_cancel = False

    def get_apk_path(self, filename, directory=None):
        return "/tmp/" + filename

    def apk_is_valid(self, path, expected_size):
        return self.existing

    def do_android_install(self, path):
        self.install_calls.append(path)
        return self.install_result

    def download_apk(self, url, filename="melo-update.apk",
                     progress_callback=None, cancel_event=None):
        self.requested.append((url, filename))
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.wait_for_cancel and cancel_event is not None:
            while not cancel_event.is_set():
                time.sleep(0.01)
            self.cancelled = True
            raise DownloadCancelled()
        if progress_callback is not None:
            progress_callback(50)
            progress_callback(100)
        return self.result

    def fetch_contributors(self, limit=8):
        return self.contributors


def wait_for(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------------------- #
# Derived text                                                                #
# --------------------------------------------------------------------------- #
def test_the_version_text_is_prefixed_once():
    assert _with_v("0.0.2") == "v0.0.2"
    assert _with_v("v0.0.2") == "v0.0.2"
    assert _with_v("") == "v0.0.0"


def test_dates_and_sizes_are_formatted_for_the_screen():
    assert _format_date("2026-11-01T12:00:00Z") == "1 Nov 2026"
    assert _format_date("") == ""
    assert _format_date("not-a-date") == "not-a-date"
    assert _format_size(48 * 1024 * 1024) == "48.00 MB"
    assert _format_size(0) == "Unknown size"


def test_the_view_model_describes_the_release():
    vm = UpdateViewModel(FakeRepository(), make_release(), "0.0.1")

    assert vm.version == "v0.0.2"
    assert vm.installed == "v0.0.1"
    assert vm.released == "1 Nov 2026"
    assert vm.size_text == "45.78 MB"
    assert vm.downloads == 12480
    assert vm.last_updated == "1 Oct 2026"
    assert vm.repo == "Fector101/Melo"
    assert vm.apk_type == "arm64-v8a"
    assert vm.release_url.endswith("/v0.0.2")
    assert vm.highlights == ["Faster scans", "Gapless playback"]
    assert vm.contributors == [OWNER]


# --------------------------------------------------------------------------- #
# Download                                                                    #
# --------------------------------------------------------------------------- #
def test_downloading_ends_ready_and_keeps_the_path(immediate_clock):
    repo = FakeRepository()
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.download()
    assert wait_for(lambda: vm.state == READY)

    assert vm.progress == 100
    assert vm.state == READY
    assert vm.failure_text == ""
    assert repo.requested == [(
        "https://example.test/melo-v0.0.2-arm64-v8a.apk",
        "melo-v0.0.2-arm64-v8a.apk")]


def test_a_valid_partial_download_skips_the_network(immediate_clock):
    repo = FakeRepository()
    repo.existing = "/tmp/already-there.apk"
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.download()

    assert vm.state == READY
    assert vm.progress == 100
    assert repo.requested == []


def test_cancelling_returns_to_available_and_keeps_the_partial(
        immediate_clock):
    repo = FakeRepository()
    repo.wait_for_cancel = True
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.download()
    assert wait_for(repo.started.is_set)
    vm.cancel()

    assert wait_for(lambda: vm.state == AVAILABLE)
    assert repo.cancelled is True
    assert vm.progress == 0
    assert vm.failure_text == ""


def test_a_failed_download_can_be_retried(immediate_clock):
    repo = FakeRepository()
    repo.error = RuntimeError("offline")
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.download()
    assert wait_for(lambda: vm.state == FAILED)
    assert "retry" in vm.failure_text.lower()

    repo.error = None
    vm.download()
    assert wait_for(lambda: vm.state == READY)


def test_a_repository_that_returns_none_is_a_failure(immediate_clock):
    repo = FakeRepository()
    repo.result = None
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.download()

    assert wait_for(lambda: vm.state == FAILED)
    assert vm.failure_text


# --------------------------------------------------------------------------- #
# Install                                                                     #
# --------------------------------------------------------------------------- #
def test_install_opens_the_installer_and_returns_to_ready(immediate_clock):
    repo = FakeRepository()
    vm = UpdateViewModel(repo, make_release(), "0.0.1")
    vm.download()
    assert wait_for(lambda: vm.state == READY)

    vm.install()

    assert repo.install_calls == ["/tmp/melo-v0.0.2-arm64-v8a.apk"]
    assert vm.state == READY
    assert vm.failure_text == ""


def test_install_failure_is_visible(immediate_clock):
    repo = FakeRepository()
    repo.install_result = False
    vm = UpdateViewModel(repo, make_release(), "0.0.1")
    vm.download()
    assert wait_for(lambda: vm.state == READY)

    vm.install()

    assert vm.state == FAILED
    assert "installer" in vm.failure_text.lower()


def test_install_does_nothing_before_the_download_is_ready():
    repo = FakeRepository()
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.install()

    assert vm.state == AVAILABLE
    assert repo.install_calls == []


# --------------------------------------------------------------------------- #
# Contributors                                                                #
# --------------------------------------------------------------------------- #
def test_contributors_are_loaded_after_the_screen_exists(immediate_clock):
    repo = FakeRepository()
    vm = UpdateViewModel(repo, make_release(), "0.0.1")

    vm.load_details()

    assert wait_for(lambda: vm.contributors == [OWNER, "bob"])
