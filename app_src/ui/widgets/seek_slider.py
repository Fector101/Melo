"""The seek bar of the player."""

from kivy.graphics import Color, Ellipse, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.slider import Slider

from ui.theme import ACCENT


class FillSlider(Slider):
    """Slider that reports a user drag, so the ticker keeps its hands off.

    ``seeking`` is True between touch-down and touch-up; while it is set the
    progress updates are skipped, which stops the 0.25s ticker from fighting
    the finger. On release the screen is asked to seek.
    """

    seeking = BooleanProperty(False)

    #: Called with the wanted position when the user lets go of the slider.
    on_seek_requested = None

    def __init__(self, **kw):
        kw.setdefault("background_width", 0)   # hides the default grey track
        super().__init__(**kw)
        with self.canvas.before:
            Color(.22, .24, .28, 1)          # track colour (lower = darker)
            self._track = RoundedRectangle(radius=[dp(1.7)])
        with self.canvas.after:
            Color(*ACCENT)
            self._thumb = Ellipse(size=(dp(18), dp(18)))
        self.bind(pos=self._upd, size=self._upd,
                  value_pos=self._upd, padding=self._upd)
        self._upd()

    def _upd(self, *_):
        pad = self.padding
        self._track.pos = (self.x + pad, self.center_y - dp(1.7))
        self._track.size = (self.width - 2 * pad, dp(3.5))
        self._thumb.pos = (self.value_pos[0] - dp(9), self.center_y - dp(9))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.seeking = True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self.seeking:
            self.seeking = False
            callback = self.on_seek_requested
            if callback is not None:
                callback(self.value)
        return super().on_touch_up(touch)
