# App class and any widget that Must talk to another screen that MUST communicate only through the screen manger
# When navigating to a screen if that screen those not exist it get created then navigated to.

from typing import Callable
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import NumericProperty

from core.insets import attach_insets


# A screen name string and a function that takes no arguments and returns a Screen instance
ScreenFactory = Callable[[], Screen]
ScreenFactories = dict[str, ScreenFactory]


class MeloScreenManager(ScreenManager):
    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._update_chip = None
        self._screen_factories: ScreenFactories = {
            "library": self.__create_library_screen,
            "update": self.__create_update_screen
        }
        attach_insets(self) # Pad the UI clear of the status bar / nav buttons Android 15+


    def on_current(self, instance, value):
        self.ensure_screen(value)
        super().on_current(instance, value)

    def register_screen(self, name: str, factory: ScreenFactory):
        self._screen_factories[name] = factory

    def ensure_screen(self, value: Screen):
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

        from ui.screens.library_screen import LibraryScreen

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

        self.library_screen = LibraryScreen(self.library_view_model, self.player_view_model)
        library_screen = self.library_screen
        self.library_view_model.set_status("Starting...")

        library_screen.apply_padding(self.inset_top, self.inset_bottom)
        self.bind(
            inset_top = lambda _,__,screen=library_screen:self.do_inset_top(screen),
            inset_bottom = lambda _,__,screen=library_screen: self.do_inset_bottom(screen)
        )
        return library_screen

    def do_inset_top(self, screen):
        # screen.ids["main_container"].padding = [0, self.inset_top, 0, self.inset_bottom]
        screen.inset_top=self.inset_top
        screen.apply_padding(self.inset_top, self.inset_bottom)

    def do_inset_bottom(self, screen):
        # screen.ids["main_container"].padding = [0, self.inset_top, 0, self.inset_bottom]
        screen.apply_padding(self.inset_top, self.inset_bottom)

    def __create_update_screen(self):
        from ui.screens.update_screen import UpdateScreen
        from viewmodels.update_view_model import UpdateViewModel
        from repositories.update_repository import UpdateRepository
        from repositories.update_notification_repository import cancel_notification

        cancel_notification()
        self.update_repository = UpdateRepository()
        self.update_view_model = UpdateViewModel(self.update_repository)
        _update_screen = self._update_screen = UpdateScreen(self.update_view_model)
        _update_screen.apply_padding(self.inset_top, self.inset_bottom)
        self.bind(
            inset_top=lambda _, __, screen=_update_screen: self.do_inset_top(screen),
            inset_bottom=lambda _, __, screen=_update_screen: self.do_inset_bottom(screen)
        )

        return self._update_screen

    def in_library_screen_show_update_chip(self):
        """A small tappable chip after the user chose Later (or went back)."""
        if self._update_chip:
            self._update_chip.show()
            return None

        from ui.widgets.update import UpdateChip

        version = self.update_view_model.version
        self._update_chip = UpdateChip(
            parent_ = self.library_screen,
            text=("Update available  \u00b7  " + version).strip(),
            on_release=lambda *_: setattr(self, "current", "update"),
            pos_hint={"right": 0.98}
        )

        self._update_chip.show()
        return None
