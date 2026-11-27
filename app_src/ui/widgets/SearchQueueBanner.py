from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout

from ui import load_kv

class SearchQueueBanner(ButtonBehavior, BoxLayout):
    """The clickable header line that points back to a search queue."""

    text = StringProperty("")
    playlist_from_search = BooleanProperty(False)

load_kv("widgets","lazy","SearchQueueBanner.kv")
