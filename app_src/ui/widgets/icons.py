"""The icons of the app.

The transport glyphs (play/pause/next/prev) are baked, anti-aliased PNGs
shipped as assets; the remaining glyphs are painted with canvas instructions so
they stay sharp on every screen density and cost nothing to ship.
"""

import math
import os

from kivy.graphics import Color, Ellipse, Line, Rectangle, Triangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

from ui.theme import FG

# Baked glyphs are real PNG assets under app_src/assets (buildozer already
# ships png files with the source). The __file__-relative lookup matches the
# kv files and works from the extracted source dir on Android.
_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets")
_IMAGE_PATHS = {
    "play": os.path.join(_ASSETS_DIR, "play.png"),
    "pause": os.path.join(_ASSETS_DIR, "pause.png"),
    "next": os.path.join(_ASSETS_DIR, "next.png"),
    "prev": os.path.join(_ASSETS_DIR, "prev.png"),
}
_IMAGE_TEXTURES = {}

# Size/position of each baked transport glyph, in dp. x/y are offsets from the
# centred position (+y moves it up).
_PLAY_IMG = {"w": dp(22), "h": dp(24), "x": dp(0), "y": dp(0)}
_PAUSE_IMG = {"w": dp(21), "h": dp(22), "x": dp(-0.5), "y": dp(0)}
_NEXT_IMG = {"w": dp(19), "h": dp(22), "x": dp(0), "y": dp(0)}
_PREV_IMG = {"w": dp(19), "h": dp(22), "x": dp(0), "y": dp(0)}
_BAKED_IMG = {
    "play": _PLAY_IMG, "pause": _PAUSE_IMG,
    "next": _NEXT_IMG, "prev": _PREV_IMG,
}

# Measured anchors (fractions of the quad's width/height) that centre the
# visible glyph in its widget at any size.
_IMAGE_SCALE = 8
_IMAGE_TEX_SIZE = 512
_IMAGE_ANCHOR_X = 0.453
_IMAGE_ANCHOR_Y = 0.419


def _baked_texture(name):
    """Load a baked PNG once (power-of-two so mipmaps work on Android)."""
    tex = _IMAGE_TEXTURES.get(name)
    if tex is None:
        from kivy.core.image import Image as CoreImage
        from kivy.core.window import Window  # noqa: F401  (ensure a GL context)
        tex = CoreImage(_IMAGE_PATHS[name], mipmap=True).texture
        _IMAGE_TEXTURES[name] = tex
    return tex


def _baked_image_box(x, y, w, h, cfg):
    """Place a baked glyph, centred, using its size/offset config."""
    scale = w / 48.
    base = _IMAGE_TEX_SIZE / float(_IMAGE_SCALE) * scale
    quad_w = base
    quad_h = base * (h / float(w))
    cx = x + w / 2. + cfg["x"]
    cy = y + h / 2. + cfg["y"]
    pos = (cx - _IMAGE_ANCHOR_X * quad_w,
           cy - _IMAGE_ANCHOR_Y * quad_h)
    return pos, (quad_w, quad_h)


class Icon(Widget):
    """A glyph drawn by hand: ``kind`` picks the shape."""

    kind = StringProperty("play")
    color = ListProperty(list(FG))
    #: Size of the drawn glyph. ``(0, 0)`` means "use the widget size", so an
    #: icon can be given a tap area bigger than what it paints.
    glyph_size = ListProperty([0, 0])
    #: Extra scale for the baked transport glyphs, which otherwise keep their
    #: fixed dp size regardless of ``size``/``glyph_size``. ``1`` (default) is
    #: the original size; only the widgets that set this are affected.
    glyph_scale = NumericProperty(1.0)

    search_line_weight = NumericProperty(1.5)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self.draw, size=self.draw, kind=self.draw,
                  color=self.draw, glyph_size=self.draw,
                  glyph_scale=self.draw)
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
        cfg = _BAKED_IMG.get(self.kind)
        s = self.glyph_scale
        ox = oy = 0
        if cfg is not None:
            gw, gh = cfg["w"] * s, cfg["h"] * s
            ox, oy = cfg["x"] * s, cfg["y"] * s
        if not gw or not gh:
            return self.x, self.y, self.width, self.height
        return (self.x + (self.width - gw) / 2. + ox,
                self.y + (self.height - gh) / 2. + oy, gw, gh)

    def draw(self, *_):
        self.canvas.clear()
        x, y, w, h = self.glyph_box()
        k = self.kind

        # Build textures before opening the canvas context: the first render
        # uses an offscreen FBO, which must not be nested inside this one.
        tex = tex_pos = tex_size = None
        cfg = _BAKED_IMG.get(k)
        if cfg is not None:
            tex = _baked_texture(k)
            draw_cfg = cfg
            if self.glyph_scale != 1:
                s = self.glyph_scale
                draw_cfg = dict(cfg, x=cfg["x"] * s, y=cfg["y"] * s)
            tex_pos, tex_size = _baked_image_box(x, y, w, h, draw_cfg)

        with self.canvas:
            Color(*self.color)
            if cfg is not None:
                Rectangle(pos=tex_pos, size=tex_size, texture=tex)
            elif k == "plus":
                t = dp(2)
                Rectangle(pos=(x, y + h / 2 - t / 2), size=(w, t))
                Rectangle(pos=(x + w / 2 - t / 2, y), size=(t, h))
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

            elif k == "search":
                lw = dp(self.search_line_weight)
                cx, cy = x + w * .40, y + h * .62
                radius = min(w, h) * .29
                pts = []
                for i in range(41):
                    angle = math.radians(i * 360 / 40)
                    pts += [cx + radius * math.cos(angle),
                            cy + radius * math.sin(angle)]
                Line(points=pts, width=lw, cap="round", joint="round")

                hx = cx + radius * math.cos(math.radians(315))
                hy = cy + radius * math.sin(math.radians(315))
                Line(points=[hx, hy, x + w * .82, y + h * .18],
                     width=lw, cap="round", joint="round")

            elif k == "back":
                lw = dp(1.8)
                mid = y + h / 2
                tip = x + w * .20
                tip_y = mid
                Line(points=[tip, tip_y, x + w * .82, tip_y],
                     width=lw, cap="round", joint="round")
                Line(points=[x + w * .45, mid + h * .27,
                             tip, tip_y,
                             x + w * .45, mid - h * .27],
                     width=lw, cap="round", joint="round")

            elif k == "close":
                lw = dp(1.8)
                Line(points=[x + w * .28, y + h * .28,
                             x + w * .72, y + h * .72],
                     width=lw, cap="round")
                Line(points=[x + w * .72, y + h * .28,
                             x + w * .28, y + h * .72],
                     width=lw, cap="round")

class TransportIcon(ButtonBehavior, Icon):
    """A drawn transport glyph that can be tapped (prev / play / next)."""
