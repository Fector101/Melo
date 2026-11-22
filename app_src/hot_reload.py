import os
from kaki.app import App
from kivy.factory import Factory
from kivy.core.window import Window
Window.always_on_top = True
from kivy.properties import BooleanProperty, StringProperty

from kivy import Config
from kivy.core.text import LabelBase
from kivy.clock import Clock

from ui import load_kv_files

from repositories.artwork_repository import ArtworkRepository
from repositories.library_repository import LibraryRepository
from repositories.playback_repository import PlaybackRepository
from repositories.player_repository import PlayerRepository
from ui.screens.library_screen import LibraryScreen
from viewmodels.library_view_model import LibraryViewModel
from viewmodels.player_view_model import PlayerViewModel
#Linux has some weirdness with the touchpad by default... remove it
options = Config.options('input')
for option in options:
    if Config.get('input', option) == 'probesysfs':
        Config.remove_option('input', option)
Window.size = (390, 740)

load_kv_files()


class MDLive(App):
    device_theme = StringProperty("dark")
    theme_preference = StringProperty("dark")
    theme_widgets = []
    KV_FILES=[
        "ui.kv.library_screen".replace(".","/") + ".kv",

    ]
    CLASSES = {
        "LibraryScreen":"ui.screens.library_screen",
    }
    AUTORELOADER_PATHS = [
        ("./ui", {"recursive": True})
    ]

    def build_app(self, *args):
        # return Factory.MyPopUp()
        # return Factory.DialogScreen(ok_callback=None)

        self.library_repository = LibraryRepository()
        self.artwork_repository = ArtworkRepository()
        self.playback_repository = PlaybackRepository()
        self.player_repository = PlayerRepository()

        self.library_view_model = LibraryViewModel(
                    self.library_repository,
                    self.artwork_repository,
                    self.player_repository,
        )
        self.player_view_model = PlayerViewModel(
            self.playback_repository,
            self.library_view_model,
            self.player_repository,
            self.artwork_repository,
        )
        return Factory.LibraryScreen(self.library_view_model,
                                            self.player_view_model)

    def on_start(self):
        # self.theme_cls.theme_style = "Light"
        # self.theme_cls.primary_palette = "Blue"
        # Clock.schedule_interval(lambda dt: self.monitor_dark_and_light_device_change(), 1)
        pass

    def monitor_dark_and_light_device_change(self):
        on_light_mode = False #is_device_on_light_mode()
        if on_light_mode:
            for each_widget in self.theme_widgets:
                each_widget.lightMode()
        else:
            for each_widget in self.theme_widgets:
                each_widget.lightDark()

MDLive().run()
