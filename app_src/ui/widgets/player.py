"""The player bar at the bottom of the screen."""

from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout


class Player(BoxLayout):
    """What is playing, the transport buttons and the seek bar.

    The widget only holds what it shows; the state comes from the player view
    model, which the screen pushes into it.
    """

    title = StringProperty("Nothing playing")
    artist = StringProperty("")
    art = StringProperty("")
    playing = BooleanProperty(False)
    loop_on = BooleanProperty(False)
    position = NumericProperty(0)  # seconds
    total = NumericProperty(0)
