# App class and any widget that Must talk to another screen that MUST communicate only through the screen manger
# When navigating to a screen if that screen those not exist it get created then navigated to.

from typing import Callable
from kivy.uix.screenmanager import ScreenManager, Screen

from core.insets import attach_insets


# A screen name string and a function that takes no arguments and returns a Screen instance
ScreenFactory = Callable[[], Screen]
ScreenFactories = dict[str, ScreenFactory]


class MeloScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._screen_factories: ScreenFactories = {
            "library": self.__create_library_screen,
            "settings": self.__create_update_screen
        }
        attach_insets(self) # Pad the UI clear of the status bar / nav buttons Android 15+


    def on_current(self, instance, value):
        self.__ensure_screen(value)
        super().on_current(instance, value)

    def register_screen(self, name: str, factory: ScreenFactory):
        self._screen_factories[name] = factory

    def __ensure_screen(self, value: Screen):
        if not self.has_screen(value):
            if value not in self._screen_factories:
                raise KeyError(f"No screen registered for '{value}'")
            screen = self._screen_factories[value]()
            screen.name = value
            self.add_widget(screen)

    def __create_library_screen(self):
        from repositories.library_repository import LibraryRepository
        from repositories.artwork_repository import ArtworkRepository
        from repositories.playback_repository import PlaybackRepository

        from viewmodels.library_view_model import LibraryViewModel
        from viewmodels.player_view_model import PlayerViewModel
        from viewmodels.permissions_view_model import PermissionsViewModel

        from ui.screens.library_screen import LibraryScreen

        self.library_repository = LibraryRepository()
        self.artwork_repository = ArtworkRepository()
        self.playback_repository = PlaybackRepository()

        # --- the view models: the state the UI renders -------------------
        self.permissions_view_model = PermissionsViewModel()
        self.library_view_model = LibraryViewModel(
            self.library_repository,
            self.artwork_repository,
            self.permissions_view_model,
        )
        self.player_view_model = PlayerViewModel(
            self.playback_repository,
            self.library_view_model,
            self.artwork_repository,
        )

        library_screen = LibraryScreen(self.library_view_model, self.player_view_model)
        return library_screen

    def __create_update_screen(self):
        from ui.screens.update_screen import UpdateScreen
        from viewmodels.update_view_model import UpdateViewModel
        from repositories.update_repository import UpdateRepository
        from repositories.update_notification_repository import cancel_notification

        cancel_notification()
        self.update_repository = UpdateRepository()
        self.update_view_model = UpdateViewModel(self._update_repository)
        self._update_screen = UpdateScreen(self.update_view_model)

        return self._update_screen

    def in_library_screen_show_update_chip(self):
        """A small tappable chip after the user chose Later (or went back)."""
        from ui.widgets.update import UpdateChip

        version = self.update_view_model.version
        _update_chip = UpdateChip(
            parent = self._update_screen,
            text=("Update available  \u00b7  " + version).strip(),
            on_release=lambda *_: setattr(self, "current", "library"),
            pos_hint={"right": 0.98}
        )

        _update_chip.show()
