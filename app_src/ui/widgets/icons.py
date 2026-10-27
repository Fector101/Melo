"""The drawn icons of the app.

The glyphs are painted with canvas instructions instead of image files, so
they stay sharp on every screen density and cost nothing to ship.
"""

import math

from kivy.graphics import Color, Ellipse, Line, Rectangle, Triangle
from kivy.metrics import dp
from kivy.properties import ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

from ui.theme import FG


class Icon(Widget):
    """A glyph drawn by hand: ``kind`` picks the shape."""

    kind = StringProperty("play")
    color = ListProperty(list(FG))
    #: Size of the drawn glyph. ``(0, 0)`` means "use the widget size", so an
    #: icon can be given a tap area bigger than what it paints.
    glyph_size = ListProperty([0, 0])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self.draw, size=self.draw, kind=self.draw,
                  color=self.draw, glyph_size=self.draw)
        self.draw()

    # Never deleting
    #     with self.canvas.before:
    #         Color(.22, 1, 1, 1)
    #         self.dev00 = Rectangle(radius=[dp(1.7)])
    #     self.bind(pos=self._upd, size=self._upd)
    #     self._upd()
    #
    # def _upd(self, *_):
    #     self.dev00.pos = (self.x, self.y)
    #     self.dev00.size = (self.width , self.height)

    def glyph_box(self):
        """Where the glyph is drawn: the widget box, or ``glyph_size`` centred."""
        gw, gh = self.glyph_size
        if not gw or not gh:
            return self.x, self.y, self.width, self.height
        return (self.x + (self.width - gw) / 2.,
                self.y + (self.height - gh) / 2., gw, gh)

    def draw(self, *_):
        self.canvas.clear()
        x, y, w, h = self.glyph_box()
        with self.canvas:
            Color(*self.color)
            k = self.kind
            if k == "plus":
                t = dp(2)
                Rectangle(pos=(x, y + h / 2 - t / 2), size=(w, t))
                Rectangle(pos=(x + w / 2 - t / 2, y), size=(t, h))
            elif k == "pause":
                bw = w * .35
                Rectangle(pos=(x + w * .14, y), size=(bw, h))
                Rectangle(pos=(x + w * .72, y), size=(bw, h))
            elif k == "play":
                Triangle(points=[x + w * .15, y, x + w * .15, y + h,
                                 x + w * .9, y + h / 2])
            elif k == "prev":
                Rectangle(pos=(x, y), size=(w * .12, h))
                Triangle(points=[x + w, y, x + w, y + h,
                                 x + w * .2, y + h / 2])
            elif k == "next":
                Rectangle(pos=(x + w * .88, y), size=(w * .12, h))
                Triangle(points=[x, y, x, y + h, x + w * .8, y + h / 2])
            elif k == "repeat":
                lw = dp(1.3)
                L, R = x + w * .15, x + w * .85
                T, B = y + h * .75, y + h * .25
                r = min(w, h) * .17  # corner radius
                ah = w * .15  # arrowhead half-height
                al = ah * 1.5  # arrowhead length

                def arc(cx, cy, a0, a1, n=10):
                    pts = []
                    for i in range(n + 1):
                        a = math.radians(a0 + (a1 - a0) * i / n)
                        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
                    return pts

                # top path: up the left side, round the corner, across to the
                # arrow
                Line(points=[L, B + al, L, T - r]
                            + arc(L + r, T - r, 180, 90)
                            + [R - al, T],
                     width=lw, cap="round", joint="round")
                Triangle(points=[R, T, R - al, T + ah, R - al, T - ah])

                # bottom path: down the right side, round the corner, back to
                # the arrow
                Line(points=[R, T - al, R, B + r]
                            + arc(R - r, B + r, 0, -90)
                            + [L + al, B],
                     width=lw, cap="round", joint="round")
                Triangle(points=[L, B, L + al, B + ah, L + al, B - ah])
            elif k == "sync":
                lw = dp(1.5)
                cx, cy = x + w / 2, y + h / 2
                R = min(w, h) * .36  # circle radius
                ah = min(w, h) * .17  # arrowhead half-width
                al = ah * 1.4  # arrowhead length
                for start in (25, 205):  # two arcs, opposite each other
                    a0, a1 = start, start + 130
                    pts = []
                    for i in range(21):
                        a = math.radians(a0 + (a1 - a0) * i / 20)
                        pts += [cx + R * math.cos(a), cy + R * math.sin(a)]
                    Line(points=pts, width=lw, cap="round", joint="round")
                    a = math.radians(a1)
                    px, py = cx + R * math.cos(a), cy + R * math.sin(a)
                    nx, ny = math.cos(a), math.sin(a)  # radial direction
                    tx, ty = -math.sin(a), math.cos(a)  # direction of travel
                    Triangle(points=[px + tx * al, py + ty * al,
                                     px + nx * ah, py + ny * ah,
                                     px - nx * ah, py - ny * ah])
            elif k == "note":
                # Beamed double eighth-note fallback: two heads, two stems and
                # one beam joining the stem tops.
                hw, hh = w * .30, h * .22  # note head size
                sw = max(dp(1.2), w * .075)  # stem width
                bh = h * .16  # beam thickness
                base = y + h * .14  # head centre line
                top = y + h * .88  # stem tops
                heads = [x + w * .22, x + w * .72]
                for cx in heads:
                    Ellipse(pos=(cx - hw / 2, base - hh / 2), size=(hw, hh))
                stems = [cx + hw * .5 - sw * .5 for cx in heads]
                for sx in stems:
                    Rectangle(pos=(sx, base), size=(sw, top - base))
                Rectangle(pos=(stems[0], top - bh),
                          size=(stems[1] + sw - stems[0], bh))


class TransportIcon(ButtonBehavior, Icon):
    """A drawn transport glyph that can be tapped (prev / play / next)."""
