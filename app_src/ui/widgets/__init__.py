"""The reusable widgets of the app.

Importing this package registers every widget class with Kivy's Factory,
which is what the KV rules and ``viewclass`` need.
"""

from ui.widgets.art import Art
from ui.widgets.fab import Fab
from ui.widgets.icons import Icon, TransportIcon
from ui.widgets.player import Player
from ui.widgets.seek_slider import FillSlider
from ui.widgets.song_row import SongRow

__all__ = ("Art", "Fab", "FillSlider", "Icon", "Player", "SongRow",
           "TransportIcon")
