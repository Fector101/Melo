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

import os
import logging
import threading

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.utils import platform

from android_notify import logger as android_notify_logger

from repositories.intent_repository import IntentRepository
from repositories.update_notification_repository import bind_update_intents, schedule_background_check

from ui import load_kv_files # TODO REMOVE, it's used for loading simple widgets
from ui.screens.manager import MeloScreenManager

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
        self.screen_manager = None

        self._update_repository = None
        self._update_view_model = None
        self._update_check_in_flight = False

    def build(self):
        load_kv_files()
        
        self.screen_manager = MeloScreenManager()
        self.screen_manager.current = "library"

        # Avoiding black after splash screen so waiting a bit before scan.
        Clock.schedule_once(self.on_startup_clock_scheduler,1)
        return self.screen_manager

    def on_startup_clock_scheduler(self, dt):
        # Bouncing the Clock so it doesn't interfere with UI generation,
        # I've tested this pattern on different Android versions and it works properly.
        self.on_intent()
        Clock.schedule_once(self._start, 0.7)
        Clock.schedule_once(self._check_updates_later, 3)

    @mainthread
    def _start(self, _dt):
        logger.info("starting: permission requests")
        self._setup_update_check_scheduler_and_bind_update_notification_listener()

        permissions_view_model = self.screen_manager.permissions_view_model
        library_view_model = self.screen_manager.library_view_model

        def __ask_for_audio_permission_and_scan(*args):
            if not permissions_view_model.has_audio_access():
                library_view_model.set_status("Requesting audio access...")
            permissions_view_model.request_audio_access(callback=lambda *_: library_view_model.scan())

        if not permissions_view_model.has_notification_access():
            library_view_model.set_status("Requesting Notification Access...")
            permissions_view_model.request_notification_access(callback=__ask_for_audio_permission_and_scan)
        else:
            __ask_for_audio_permission_and_scan()

    def _setup_update_check_scheduler_and_bind_update_notification_listener(self):
        """Schedule the Java background check and listen for its tap."""
        schedule_background_check()
        bind_update_intents(self.handle_update_intent)

    def on_intent(self):
        intent_repo = IntentRepository()
        payload = intent_repo.read_update_intent()
        self.handle_update_intent(payload)

    def handle_update_intent(self, payload):
        """The user tapped the background update notification."""
        if not payload:
            return
        logger.info("Update notification tapped: %s", payload)
        self.screen_manager.current = "update"

    def _check_updates_later(self, _dt=None):
        """Run the update check off the UI thread, after startup settles."""
        def _check_updates():
            """Build and open the update screen if new version exists (only once, then reuse it)."""

            from viewmodels.update_view_model import UpdateViewModel
            from repositories.update_repository import UpdateRepository

            update_view_model = UpdateViewModel(UpdateRepository())

            if update_view_model.has_new_version:
                Clock.schedule_once(lambda _dt: setattr(self.screen_manager,"current","update"), 0)

        if platform == "android" or os.environ.get("MELO_UPDATE_API_URL"):
            threading.Thread(target=_check_updates, daemon=True).start()

    def on_stop(self):
        update_view_model = getattr(self.screen_manager, "update_view_model", None)
        player_view_model = self.screen_manager.player_view_model

        if update_view_model is not None:
            update_view_model.shutdown()
        player_view_model.end_operations()


if __name__ == "__main__":
    MeloApp().run()
