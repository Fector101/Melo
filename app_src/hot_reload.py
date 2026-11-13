import os

from kaki.app import App
from kivy import Config
from kivy.factory import Factory
from kivy.core.window import Window
from kivy.properties import ListProperty
from kivy.utils import get_color_from_hex as hex_

from ui import load_kv_files

#Linux has some weirdness with the touchpad by default... remove it
options = Config.options('input')
for option in options:
    if Config.get('input', option) == 'probesysfs':
        Config.remove_option('input', option)


Window.size = (390, 740)
Window.always_on_top = True


class MDLive(App):
    bg = ListProperty(hex_("#1c1f26"))
    accent = ListProperty(hex_("#7cc4f5"))
    KV_FILES=[
        "ui.kv.library_screen".replace(".","/") + ".kv",

    ]
    CLASSES = {
       
        "LibraryScreen": "ui.screens.library_screen",
    }
    AUTORELOADER_PATHS = [
        ("./ui", {"recursive": True})
    ]

    def build_app(self, *args):
        load_kv_files()

        from repositories.library_repository import LibraryRepository
        from repositories.artwork_repository import ArtworkRepository
        from repositories.playback_repository import PlaybackRepository

        from viewmodels.library_view_model import LibraryViewModel
        from viewmodels.player_view_model import PlayerViewModel
        from viewmodels.permissions_view_model import PermissionsViewModel
        # from viewmodels.inset_view_model import InsetViewModel

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
        return Factory.LibraryScreen(self.library_view_model, self.player_view_model)

    def on_start(self):
        pass

    def monitor_dark_and_light_device_change(self):
        on_light_mode = False
        if on_light_mode:
            for each_widget in self.theme_widgets:
                each_widget.lightMode()
        else:
            for each_widget in self.theme_widgets:
                each_widget.lightDark()

MDLive().run()

