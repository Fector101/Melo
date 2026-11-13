"""The screen manager: it builds the screens and talks between them.

A screen is built the first time it is navigated to and reused after that.
The manager is also where the app is wired: it builds the repositories, the
view models and the screens, so ``main`` only runs the lifecycle.

A screen that has to talk to another one does it through this manager (never
directly). The manager owns the update check's view model, because the update
screen may only be built after that check has found a newer release.
"""

from typing import Callable

from kivy.properties import NumericProperty
from kivy.uix.screenmanager import Screen, ScreenManager

from core.insets import attach_insets

# A screen name and a function that takes no arguments and returns a Screen.
ScreenFactory = Callable[[], Screen]
ScreenFactories = dict[str, ScreenFactory]


class MeloScreenManager(ScreenManager):
    """A ``ScreenManager`` that builds its screens (and their view models)."""

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.permissions = None
        self.library_repository = None
        self.artwork_repository = None
        self.playback_repository = None
        self.library_view_model = None
        self.player_view_model = None
        self.update_view_model = None
        self.library_screen = None

        self._screen_factories: ScreenFactories = {
            "library": self.__create_library_screen,
            "update": self.__create_update_screen
        }
        attach_insets(self) # Pad the UI clear of the status bar / nav buttons (Android 15+).
        self.bind(inset_top=self._apply_insets_to_screens, inset_bottom=self._apply_insets_to_screens)

    def register_screen(self, name: str, factory: ScreenFactory):
        """Add or replace the factory of the screen called ``name``."""
        self._screen_factories[name] = factory

    def on_current(self, instance, value):
        # Create the screen before ``super().on_current`` asks for it.
        self.ensure_screen(value)
        super().on_current(instance, value)

    def ensure_screen(self, name: str):
        """Build and add the screen called ``name`` if it does not exist yet."""
        if not name or self.has_screen(name):
            return
        if name not in self._screen_factories:
            raise KeyError(f"No screen registered for '{name}'")
        screen = self._screen_factories[name]()
        screen.name = name
        self.add_widget(screen)
        self._apply_insets_to_screens()

    # ------------------------------------------------------------------ #
    # The update                                                          #
    # ------------------------------------------------------------------ #
    def check_for_update(self):
        """Build the update view model; call this from a worker thread.

        Returns whether there is a newer release. The screen factory reuses
        the view model, so the network is asked exactly once.
        """
        from repositories.update_repository import UpdateRepository
        from viewmodels.update_view_model import UpdateViewModel

        update_view_model = UpdateViewModel(UpdateRepository())
        if not update_view_model.has_new_version:
            update_view_model.shutdown()
            return False
        self.update_view_model = update_view_model
        return True

    # ------------------------------------------------------------------ #
    # The screens (the factories, called on first use)                    #
    # ------------------------------------------------------------------ #
    def __create_library_screen(self):
        from repositories.artwork_repository import ArtworkRepository
        from repositories.library_repository import LibraryRepository
        from repositories.playback_repository import PlaybackRepository
        from ui.screens.library_screen import LibraryScreen
        from viewmodels.library_view_model import LibraryViewModel
        from viewmodels.player_view_model import PlayerViewModel

        self.library_repository = LibraryRepository()
        self.artwork_repository = ArtworkRepository()
        self.playback_repository = PlaybackRepository()

        # --- the view models: the state the UI renders -------------------
        self.library_view_model = LibraryViewModel(
            self.library_repository,
            self.artwork_repository,
        )
        self.player_view_model = PlayerViewModel(
            self.playback_repository,
            self.library_view_model,
            self.artwork_repository,
        )

        self.library_screen = LibraryScreen(self.library_view_model,
                                            self.player_view_model)
        self.library_view_model.set_status("Starting...")
        return self.library_screen

    def __create_update_screen(self):
        from repositories.update_notification_repository import cancel_notification
        from ui.screens.update_screen import UpdateScreen

        if self.update_view_model is None:
            # Only the update check opens this screen, so this is a bug.
            raise RuntimeError("the update check must run before the screen opens")
        cancel_notification()
        return UpdateScreen(self.update_view_model)

    # ------------------------------------------------------------------ #
    # Insets                                                              #
    # ------------------------------------------------------------------ #
    def _apply_insets_to_screens(self, *_):
        """Give every screen that pads itself the current window insets."""
        for screen in self.screens:
            apply_padding = getattr(screen, "apply_padding", None)
            if apply_padding is not None:
                apply_padding(self.inset_top, self.inset_bottom)
