"""The cover of a track (or the glyph that stands in for a missing one)."""

import os

from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image

from ui.theme import TILE_BG


class Art(FloatLayout):
    """The cover art of a track.

    The real cover is an image child; when a track has none, the note glyph
    from the KV rule stays visible.
    """

    bg = ListProperty(list(TILE_BG))  # neutral tile behind the note glyph
    source = StringProperty("")
    art_loaded = BooleanProperty(False)

    def __init__(self, **kw):
        self._image = None
        super().__init__(**kw)
        self.bind(source=self._load)
        self._load()

    def _load(self, *_):
        """Show the cover Image when there is one, else keep the note glyph.

        Only the Image is managed here: the fallback `Icon` comes from the KV
        rule, so it must not be wiped on every reload.
        """
        image = getattr(self, "_image", None)
        if image is not None:
            self.remove_widget(image)
            self._image = None
        if self.source and os.path.exists(self.source):
            self._image = Image(source=self.source, mipmap=True,
                                fit_mode="cover",
                                size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            self.add_widget(self._image)
        self.art_loaded = self._image is not None
