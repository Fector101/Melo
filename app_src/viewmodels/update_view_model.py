"""The update screen's state and commands.

The view model is only imported when a newer release has already been found,
so it may import Kivy and the updater repository without affecting startup.
"""

import logging
import threading
from datetime import datetime

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.properties import ListProperty, NumericProperty, StringProperty

from models.release import parse_highlights
from repositories.update_repository import (DownloadCancelled, OWNER)

logger = logging.getLogger("melo.update")

#: The states the update content knows how to render.
AVAILABLE = "available"
DOWNLOADING = "downloading"
READY = "ready"
INSTALLING = "installing"
FAILED = "failed"


def _with_v(value):
    text = str(value or "0.0.0")
    return text if text.startswith("v") else "v" + text


def _format_date(value):
    """ISO date from GitHub -> ``1 Nov 2026`` (empty when unusable)."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return f"{parsed.day} {parsed.strftime('%b %Y')}"
    except ValueError:
        return text[:10]


def _format_size(size):
    size = int(size or 0)
    if size <= 0:
        return "Unknown size"
    return f"{size / (1024 * 1024):.2f} MB"


class UpdateViewModel(EventDispatcher):
    """Observable state for one offered release plus its download/install.

    The download runs on a daemon thread; every property that Kivy reads is
    updated through ``Clock.schedule_once`` so it changes on the Kivy thread.
    """

    state = StringProperty(AVAILABLE)
    progress = NumericProperty(0)
    contributors = ListProperty([OWNER])
    failure_text = StringProperty("")

    version = StringProperty("")
    installed = StringProperty("")
    released = StringProperty("")
    size_text = StringProperty("")
    downloads = NumericProperty(0)
    last_updated = StringProperty("")
    repo = StringProperty("")
    apk_type = StringProperty("")
    release_url = StringProperty("")
    highlights = ListProperty([])

    def __init__(self, repository, release, installed_version, **kwargs):
        super().__init__(**kwargs)
        self.repository = repository
        self.release = release
        self._apk_path = None
        self._cancel_event = None
        self._download_thread = None
        self._details_thread = None

        self.version = _with_v(release.version)
        self.installed = _with_v(installed_version)
        self.released = _format_date(release.published_at) or "Unknown"
        self.size_text = _format_size(release.asset.size)
        self.downloads = int(release.asset.downloads or 0)
        self.last_updated = (
            _format_date(release.asset.updated_at or release.published_at)
            or "Unknown")
        self.repo = release.repo
        self.apk_type = release.asset.abi or "universal"
        self.release_url = (
            release.html_url
            or f"https://github.com/{release.repo}/releases/tag/"
               f"{release.tag or self.version}")
        self.highlights = parse_highlights(release.notes or release.body)

    # ------------------------------------------------------------------ #
    # Details loaded after the screen is already visible                  #
    # ------------------------------------------------------------------ #
    def load_details(self):
        """Fetch contributors in the background; the screen opened already."""
        if self._details_thread is not None and self._details_thread.is_alive():
            return
        self._details_thread = threading.Thread(
            target=self._load_contributors, daemon=True)
        self._details_thread.start()

    def _load_contributors(self):
        try:
            contributors = self.repository.fetch_contributors()
        except Exception:
            logger.exception("Could not load contributors")
            return
        if contributors:
            Clock.schedule_once(
                lambda _dt: self._set_contributors(contributors), 0)

    def _set_contributors(self, contributors):
        self.contributors = list(contributors)

    # ------------------------------------------------------------------ #
    # Commands                                                            #
    # ------------------------------------------------------------------ #
    def download(self):
        """Start (or resume) the download, or jump straight to Install."""
        if self.state in (DOWNLOADING, INSTALLING):
            return

        existing = self.repository.get_apk_path(self.release.asset.name)
        if self.repository.apk_is_valid(existing, self.release.asset.size):
            self._apk_path = existing
            self.failure_text = ""
            self.progress = 100
            self.state = READY
            return

        self._cancel_event = threading.Event()
        self.failure_text = ""
        self.progress = 0
        self.state = DOWNLOADING
        self._download_thread = threading.Thread(
            target=self._download_worker, daemon=True)
        self._download_thread.start()

    def cancel(self):
        """Ask the worker to stop after the current chunk; keep the file."""
        if self.state == DOWNLOADING and self._cancel_event is not None:
            self._cancel_event.set()

    def install(self):
        """Open the system installer for the downloaded APK."""
        if self.state != READY:
            return
        path = self._apk_path or self.repository.get_apk_path(
            self.release.asset.name)
        self.state = INSTALLING
        try:
            started = bool(self.repository.do_android_install(path))
        except Exception:
            logger.exception("Could not start the installer")
            started = False
        if started:
            self.failure_text = ""
            self.state = READY
        else:
            self.failure_text = "Could not open the installer."
            self.state = FAILED

    def shutdown(self):
        """Stop a download when the app is closing."""
        self.cancel()

    # ------------------------------------------------------------------ #
    # Worker callbacks                                                    #
    # ------------------------------------------------------------------ #
    def _download_worker(self):
        try:
            path = self.repository.download_apk(
                self.release.asset.download_url,
                filename=self.release.asset.name,
                progress_callback=self._on_progress,
                cancel_event=self._cancel_event,
            )
        except DownloadCancelled:
            Clock.schedule_once(lambda _dt: self._finish_cancelled(), 0)
            return
        except Exception:
            logger.exception("Update download failed")
            Clock.schedule_once(
                lambda _dt: self._finish_failed(
                    "Download failed. Check your connection and retry."), 0)
            return

        if path:
            Clock.schedule_once(lambda _dt: self._finish_ready(path), 0)
        else:
            Clock.schedule_once(
                lambda _dt: self._finish_failed(
                    "Download failed. Check your connection and retry."), 0)

    def _on_progress(self, percent):
        percent = max(0, min(100, int(percent)))
        Clock.schedule_once(lambda _dt: self._set_progress(percent), 0)

    def _set_progress(self, percent):
        if self.state == DOWNLOADING:
            self.progress = percent

    def _finish_ready(self, path):
        self._apk_path = path
        self._cancel_event = None
        self.failure_text = ""
        self.progress = 100
        self.state = READY

    def _finish_cancelled(self):
        self._cancel_event = None
        self.failure_text = ""
        self.progress = 0
        self.state = AVAILABLE

    def _finish_failed(self, message):
        self._cancel_event = None
        self.failure_text = message
        self.state = FAILED
