"""Melo - a music player for Android.

This module is the composition root: it builds the repositories, the view
models and the screen, and hands them to each other. Everything else lives
in one of these layers:

    core/          platform glue (Android insets, the JVM)
    models/        the domain model
    repositories/  device access (MediaStore, artwork, the audio engine)
    viewmodels/    observable state and commands
    ui/            widgets, screens and KV rules
"""

import logging

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.utils import platform

from android_notify import logger as android_notify_logger
from core.insets import attach_insets
from repositories.artwork_repository import ArtworkRepository
from repositories.library_repository import LibraryRepository
from repositories.permissions_repository import PermissionsRepository
from repositories.playback_repository import PlaybackRepository
from ui import load_kv_files
from ui.screens.library_screen import LibraryScreen
from ui.theme import BG
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel

android_notify_logger.setLevel(logging.DEBUG)
logger = logging.getLogger("melo")

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

if platform not in ("android", "ios"):
    Window.size = (390, 740)


class MeloApp(App):
    """The application; it only wires the layers together."""

    def build(self):
        Window.clearcolor = BG
        load_kv_files()

        # --- the repositories: the only ones that talk to the device ------
        self.library_repository = LibraryRepository()
        self.artwork_repository = ArtworkRepository(self.user_data_dir)
        self.permissions_repository = PermissionsRepository()
        self.playback_repository = PlaybackRepository()

        # --- the view models: the state the UI renders -------------------
        self.library_view_model = LibraryViewModel(
            self.library_repository,
            self.artwork_repository,
            self.permissions_repository,
        )
        self.player_view_model = PlayerViewModel(
            self.playback_repository,
            self.library_view_model,
            self.artwork_repository,
        )

        # --- the view ---------------------------------------------------
        self.root_ui = LibraryScreen(self.library_view_model, self.player_view_model)
        self.player_view_model.start()
        self.library_view_model.set_status("Starting...")

        # Pad the UI clear of the status bar / nav buttons (no-op off
        # Android).
        attach_insets(self.root_ui)

        # Avoiding black after splash screen so waiting a bit before scan.
        Clock.schedule_once(self.weird_clock_issue,1)
        return self.root_ui

    def weird_clock_issue(self, dt):
        # Clock fired immediately reaching shedule line, so schedule again after that.
        Clock.schedule_once(self._start, 0.7)
        
    @mainthread
    def _start(self, _dt):
        logger.info("starting: request audio permission")
        self.library_view_model.scan()

    def on_stop(self):
        self.player_view_model.stop()
        self.playback_repository.release()


if __name__ == "__main__":
    MeloApp().run()
