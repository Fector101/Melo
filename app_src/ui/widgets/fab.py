"""The round button that starts a scan of the device."""

from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout


class Fab(ButtonBehavior, FloatLayout):
    """A floating action button; the screen decides what it does."""
