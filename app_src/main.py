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
        # self.player_view_model.start()
        self.library_view_model.set_status("Starting...")

        # Pad the UI clear of the status bar / nav buttons (no-op off
        # Android).
        attach_insets(self.root_ui)

        # The update check is deliberately late: startup and the first scan
        # must not wait on the network. The updater modules are imported only
        # after this check has found a newer release.
        self._update_repository = None
        self._update_view_model = None
        self._update_screen = None
        self._update_chip = None
        self._update_chip_class = None
        self.root_ui.bind(size=self._position_update_chip,
                          inset_top=self._position_update_chip,
                          inset_right=self._position_update_chip)
        Clock.schedule_once(self._check_updates_later, 6)

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

    # ------------------------------------------------------------------ #
    # Self-update                                                         #
    # ------------------------------------------------------------------ #
    def _check_updates_later(self, _dt):
        """Run the update check off the UI thread, after startup settles."""
        if platform != "android" and not os.environ.get("MELO_UPDATE_API_URL"):
            return
        threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        try:
            from repositories.update_repository import UpdateRepository

            repository = UpdateRepository()
            release = repository.check_for_update()
        except Exception:
            logger.exception("Update check failed")
            return
        if release is None:
            return
        Clock.schedule_once(
            lambda _dt: self._show_update(repository, release), 0)

    def _show_update(self, repository, release):
        """Build and open the update screen (only once, then reuse it)."""
        if self._update_screen is not None:
            self._open_update_screen()
            return
        try:
            from ui.screens.update_screen import UpdateScreen
            from ui.widgets.update import UpdateChip
            from viewmodels.update_view_model import UpdateViewModel

            installed = repository.get_installed_version()
            view_model = UpdateViewModel(repository, release, installed)
            screen = UpdateScreen(view_model)
        except Exception:
            logger.exception("Could not build the update screen")
            return

        screen.bind(on_dismiss=lambda *_: self._show_update_chip())
        self._update_repository = repository
        self._update_view_model = view_model
        self._update_screen = screen
        self._update_chip_class = UpdateChip
        self._bind_update_insets(screen)
        screen.open()
        self._remove_update_chip()

    def _bind_update_insets(self, screen):
        """Forward the root's live insets to the modal (no second JNI hook)."""
        root = self.root_ui
        for name in ("inset_top", "inset_bottom", "inset_left", "inset_right"):
            setattr(screen, name, getattr(root, name))
            root.bind(**{
                name: lambda _instance, value, prop=name: setattr(
                    screen, prop, value)
            })

    def _show_update_chip(self):
        """A small tappable chip after the user chose Later (or went back)."""
        if self._update_chip is not None or self._update_screen is None:
            return
        chip_class = self._update_chip_class
        if chip_class is None:
            return
        version = self._update_view_model.version if self._update_view_model else ""
        chip = chip_class(text=("Update available  \u00b7  " + version).strip())
        chip.bind(on_release=lambda *_: self._open_update_screen())
        chip.bind(size=self._position_update_chip)
        self._update_chip = chip
        self.root_ui.add_widget(chip)
        self._position_update_chip()

    def _position_update_chip(self, *_):
        chip = self._update_chip
        if chip is None:
            return
        root = self.root_ui
        chip.x = root.width - chip.width - dp(12) - root.inset_right
        chip.y = root.height - chip.height - dp(12) - root.inset_top

    def _remove_update_chip(self):
        chip = self._update_chip
        if chip is not None:
            self.root_ui.remove_widget(chip)
            self._update_chip = None

    def _open_update_screen(self):
        self._remove_update_chip()
        if self._update_screen is not None:
            self._update_screen.open()

    def on_stop(self):
        if self._update_view_model is not None:
            self._update_view_model.shutdown()
        self.player_view_model.end_operations()


if __name__ == "__main__":
    MeloApp().run()
