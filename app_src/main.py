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
from repositories.update_notification_repository import (bind_update_intents,
                                                         cancel_notification,
                                                         read_update_intent,
                                                         schedule_background_check)
from ui import load_kv_files
from ui.screens.library_screen import LibraryScreen
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel

android_notify_logger.setLevel(logging.WARNING)
logger = logging.getLogger("melo")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if platform not in ("android", "ios"):
    Window.size = (390, 740)


class MeloApp(App):
    """The application; it only wires the layers together."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # All Classes and logical setup to avoid doing unnecessary work, to make sure there's no blank black screen after splash screen
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
        self._update_check_in_flight = False

    def build(self):
        create screen manager 
        tell it to show the first screen library screen
        it internally checks if the exists if not it creates it else it just opens it
        it also creates it Viewmodels when going to that screen including the first screen for cleaness sack scoping it's creation 
        the update badge comes from update screen and attaches to library screen
        the app class and other screens only talks to the screen manager class and not the individual screen 
        there should be no class on App class apart from build, start, pause, stop
            
        load_kv_files()
            

        # --- the repositories: the only ones that talk to the device ------
        self.library_repository = LibraryRepository()
        self.artwork_repository = ArtworkRepository()
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
        attach_insets(self.scrren_manager)

        # Avoiding black after splash screen so waiting a bit before scan.
        Clock.schedule_once(self.on_startup_clock_scheduler,1)
        return self.screen_manger

    def on_startup_clock_scheduler(self, dt):
        # Bouncing the Clock so it doesn't interfere with UI generation,
        # I've tested this pattern on different Android versions and it works properly.
        self._consume_launch_update_intent()
        Clock.schedule_once(self._start, 0.7)
        Clock.schedule_once(self._check_updates_later, 3)

    @mainthread
    def _start(self, _dt):
        logger.info("starting: permission requests")
        self._setup_update_check_and_bind_notification_listener()

        def __ask_for_audio_permission_and_scan(*args):
            if not self.permissions_repository.has_audio_access():
                self.library_view_model.set_status("Requesting audio access...")
            self.permissions_repository.request_audio_access(callback=lambda *_: self.library_view_model.scan())
        
        if not self.permissions_repository.has_notification_access():
            self.library_view_model.set_status("Requesting Notification Access...")
            self.permissions_repository.request_notification_access(callback=__ask_for_audio_permission_and_scan)
        else:
            __ask_for_audio_permission_and_scan()
    def _setup_update_check_and_bind_notification_listener(self):
        """Schedule the Java background check and listen for its tap."""
        if platform != "android":
            return
        schedule_background_check()
        bind_update_intents(self._on_update_intent)
        # A tap that launched a cold start is read once the UI exists.

    def _consume_launch_update_intent(self):
        payload = read_update_intent()
        if payload:
            self._on_update_intent(payload)

    def _on_update_intent(self, payload):
        """The user tapped the background update notification."""
        if not payload:
            return
        logger.info("Update notification tapped: %s", payload)
        if self._update_view_model is not None and self._update_view_model.has_new_version:
            Clock.schedule_once(lambda _dt: self._show_update_screen(), 0)
            return
        threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates_later(self, _dt):
        """Run the update check off the UI thread, after startup settles."""
        if platform == "android" or os.environ.get("MELO_UPDATE_API_URL"):
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        """Build and open the update screen if new version exists (only once, then reuse it)."""
        if self._update_check_in_flight:
            return
        self._update_check_in_flight = True
        try:
            from viewmodels.update_view_model import UpdateViewModel
            from repositories.update_repository import UpdateRepository

            self._update_repository = UpdateRepository()
            self._update_view_model = UpdateViewModel(self._update_repository)

            if self._update_view_model.has_new_version:
                Clock.schedule_once(lambda _dt: self._show_update_screen(), 0)
        finally:
            self._update_check_in_flight = False

    def _show_update_screen(self):
        cancel_notification()
        if self._update_screen is not None:
            self._update_screen.open()
            self._remove_update_chip()
            return
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
        cancel_notification()
        self._remove_update_chip()
        self._update_screen.open()

    def on_stop(self):
        if self._update_view_model is not None:
            self._update_view_model.shutdown()
        self.player_view_model.end_operations()


if __name__ == "__main__":
    MeloApp().run()
