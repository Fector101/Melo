"""One row of the song list."""

from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior

from ui.theme import ACCENT, FG, FG_DIM


class SongRow(RecycleDataViewBehavior, ButtonBehavior, BoxLayout):
    """A track in the list.

    The RecycleView reuses rows, so ``refresh_view_attrs`` re-points a row at
    a new track when it is recycled.
    """

    index = NumericProperty(0)
    title = StringProperty()
    artist = StringProperty()
    duration = StringProperty("0:00")
    path = StringProperty("")
    art = StringProperty("")
    active = BooleanProperty(False)
    fg = ListProperty(list(FG))
    fg_dim = ListProperty(list(FG_DIM))

    #: Called with the row's path when the row is tapped. The screen sets
    #: it; a recycled row keeps it until the next refresh.
    on_select = None

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(active=self._style)
        self._style()

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        # base class copies every key of `data` onto the matching property
        return super().refresh_view_attrs(rv, index, data)

    def on_release(self, touch):
        callback = self.on_select
        if callback is not None:
            callback(self.path)

    def _style(self, *_):
        if self.active:
            self.fg, self.fg_dim = list(ACCENT), list(ACCENT)
        else:
            self.fg, self.fg_dim = list(FG), list(FG_DIM)
