"""The single, app-wide home of the player bar.

Only one :class:`~ui.widgets.player.Player` widget exists. It lives in this
host above the screen manager, so navigating between library and search never
creates or reparents it. The view-model bindings also happen once here instead
of being repeated by every screen that wants a player bar.
"""

from kivy.properties import (BooleanProperty, NumericProperty,
                             ObjectProperty)
from kivy.uix.floatlayout import FloatLayout

from ui.theme import PLAYER_HEIGHT
from ui.widgets.player import Player

#: Screens that show the bar. The update screen has no slot for it.
PLAYER_SCREENS = ("library", "search")


class PlayerHost(FloatLayout):
    """Owns the one player bar and keeps it in sync with the player view model."""

    player = ObjectProperty(None)
    inset_bottom = NumericProperty(94.1)
    visible = BooleanProperty(True)

    def __init__(self, player_view_model, manager=None, **kwargs):
        super().__init__(**kwargs)
        self.view_model = player_view_model
        self.manager = manager
        self._screen = None

        self.player = Player(size_hint=(1, None), height=PLAYER_HEIGHT)
        self.add_widget(self.player)

        self._bind_view_model()
        self._bind_widgets()
        self.bind(inset_bottom=self._place,
                  visible=self._place,
                  pos=self._place,
                  size=self._place)
        
        manager.bind(inset_bottom=self._on_screen_inset)
        manager.bind(current_screen=self._on_current_screen)
        self._on_current_screen(manager, manager.current_screen)
        self._place()

    # The view model -> the widget reciveing data from vm
    # ------------------------------------------------------------------ #
    def _bind_view_model(self):
        vm = self.view_model
        vm.bind(title=self._on_state,
                artist=self._on_state,
                art=self._on_state,
                is_playing=self._on_state,
                loop_enabled=self._on_state,
                duration=self._on_state,
                current_track=self._on_state,
                position=self._on_position)
        self._on_state(vm, None)
        self._on_position(vm, vm.position)

    def _on_state(self, _instance, _value):
        vm = self.view_model
        bar = self.player
        bar.title = vm.title
        bar.artist = vm.artist
        bar.art = vm.art
        bar.playing = vm.is_playing
        bar.loop_on = vm.loop_enabled
        bar.total = vm.duration

    def _on_position(self, _instance, value):
        self.player.position = value

    # The widget -> the view model  sending data to vms
    # ------------------------------------------------------------------ #
    def _bind_widgets(self):
        vm = self.view_model
        ids = self.player.ids
        ids.prev_button.bind(on_release=lambda *_: vm.previous_track())
        ids.play_button.bind(on_release=lambda *_: vm.toggle_play_pause())
        ids.next_button.bind(on_release=lambda *_: vm.next_track())
        ids.repeat_button.bind(on_release=lambda *_: vm.toggle_loop())
        ids.seek.on_seek_requested = vm.seek
        ids.seek.bind(seeking=lambda _widget, value: vm.set_seeking(value))

    def _on_current_screen(self, _manager, screen):
        self._screen = screen
        if screen: # hot_reload patch
            self.visible = screen.name in PLAYER_SCREENS

    def _on_screen_inset(self, _screen, value):
        self.inset_bottom = value

    def _place(self, *_):
        """Pin the bar to the bottom edge, above the navigation buttons."""
        bar = self.player
        bar.width = self.width
        bar.height = PLAYER_HEIGHT
        y = self.inset_bottom if self.visible else -PLAYER_HEIGHT
        # Child coordinates are relative to the host; the host itself fills
        # the root at (0, 0).
        bar.pos = (0, y)


__all__ = ("PLAYER_HEIGHT", "PLAYER_SCREENS", "PlayerHost")
