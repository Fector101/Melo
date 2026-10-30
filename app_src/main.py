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
import os
import threading

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.metrics import dp
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
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if platform not in ("android", "ios"):
    Window.size = (390, 740)


class MeloApp(App):
    """The application; it only wires the layers together."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # The update check is deliberately late: startup and the first scan
        # must not wait on the network. The updater modules are imported only
        # after this check has found a newer release.
        self.root_ui = None
        self.player_view_model = None
        self.library_view_model = None
        self.playback_repository = None
        self.artwork_repository = None
        self.library_repository = None
        self.permissions_repository = None
        self._update_repository = None
        self._update_view_model = None
        self._update_screen = None
        self._update_chip = None
        self._update_chip_class = None

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
        self.library_view_model.set_status("Starting...")

        # Pad the UI clear of the status bar / nav buttons Android 15+
        attach_insets(self.root_ui)

        # Avoiding black after splash screen so waiting a bit before scan.
        Clock.schedule_once(self.weird_clock_issue,1)
        return self.root_ui

    def weird_clock_issue(self, dt):
        # Clock fired immediately reaching schedule line, so scheduling again here after that.
        Clock.schedule_once(self._start, 0.7)
        Clock.schedule_once(self._check_updates_later, 3)

    @mainthread
    def _start(self, _dt):
        logger.info("starting: request audio permission")
        self.library_view_model.scan()

    def _check_updates_later(self, _dt):
        """Run the update check off the UI thread, after startup settles."""
        if platform == "android" or os.environ.get("MELO_UPDATE_API_URL"):
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        """Build and open the update screen if new version exists (only once, then reuse it)."""
        from viewmodels.update_view_model import UpdateViewModel
        from repositories.update_repository import UpdateRepository

        self._update_repository = UpdateRepository()
        self._update_view_model = UpdateViewModel(self._update_repository)

        if self._update_view_model.has_new_version:
            Clock.schedule_once(lambda _dt: self._show_update_screen(), 0)

    def _show_update_screen(self):
        try:
            from ui.screens.update_screen import UpdateScreen
            self._update_screen = UpdateScreen(self._update_view_model)
        except Exception as error_building_update_screen:
            logger.exception("Could not build the update screen: %s", error_building_update_screen)
            return

        self._update_screen.bind(on_dismiss=lambda *_: self._show_update_chip())
        attach_insets(self._update_screen)
        self._update_screen.open()
        self._remove_update_chip()

    def _show_update_chip(self):
        """A small tappable chip after the user chose Later (or went back)."""

        from ui.widgets.update import UpdateChip

        version = self._update_view_model.version if self._update_view_model else ""
        self._update_chip = UpdateChip(
            text=("Update available  \u00b7  " + version).strip(),
            on_release=lambda *_: self._open_update_screen(),
            pos_hint={"right":0.98}
        )
        self._update_chip.y = self.root_ui.height - self._update_chip.height - dp(12) - self.root_ui.inset_top
        self.root_ui.add_widget(self._update_chip)

    def _remove_update_chip(self):
        if self._update_chip:
            self.root_ui.remove_widget(self._update_chip)
            self._update_chip = None

    def _open_update_screen(self):
        self._remove_update_chip()
        self._update_screen.open()

    def on_stop(self):
        if self._update_view_model is not None:
            self._update_view_model.shutdown()
        self.player_view_model.end_operations()


if __name__ == "__main__":
    MeloApp().run()
