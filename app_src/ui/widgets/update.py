"""Widgets that belong to the update screen only.

They live in their own module (and are not imported by ``ui.widgets``) so the
update UI is not built or even parsed until a newer release exists.
"""

import re
from math import atan2, cos, hypot, pi, sin, sqrt

from kivy.graphics import Color, Line, Mesh
from kivy.graphics.tesselator import TYPE_POLYGONS, WINDING_ODD, Tesselator
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty, ObjectProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from ui import theme as THEME

#: The small palette used for contributor initials.
AVATAR_TINTS = (
    [.25, .45, .75, 1],
    [.10, .50, .15, 1],
    [.75, .28, .22, 1],
)


class UpdateCard(BoxLayout):
    """A rounded, filled container."""

    bg = ListProperty(list(THEME.UPDATE_CARD_BG))
    radius = NumericProperty(dp(12))


class UpdateClickableCard(ButtonBehavior, UpdateCard):
    """A card that can be tapped."""


class UpdatePill(ButtonBehavior, Label):
    """A rounded button whose outline can be switched on per instance."""

    bg = ListProperty(list(THEME.UPDATE_ACCENT))
    outline = NumericProperty(0)
    radius = NumericProperty(dp(10))


class UpdateAvatar(Widget):
    """A circle with a contributor's initial."""

    letter = StringProperty("")
    tint = ListProperty([.3, .3, .3, 1])


class UpdateChip(ButtonBehavior, Label):
    """The small "Update available" chip on the library screen."""

    bg = ListProperty(list(THEME.UPDATE_ACCENT))
    radius = NumericProperty(dp(17))


# --------------------------------------------------------------------------- #
# Vector icons (no icon font or image needed)                                 #
# --------------------------------------------------------------------------- #
# The GitHub mark, flattened from its 16x16 SVG path.
GITHUB_PATH = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
    "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13"
    "-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66"
    ".07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
    "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 "
    "1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 "
    "1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 "
    "1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"
)
_GH_POLY = None


def _cubic(p0, p1, p2, p3, n=14):
    out = []
    for index in range(1, n + 1):
        t = index / n
        u = 1 - t
        out.append((
            u ** 3 * p0[0] + 3 * u * u * t * p1[0]
            + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1] + t ** 3 * p3[1],
        ))
    return out


def _arc(p0, radius, sweep, p1, n=24):
    (x1, y1), (x2, y2) = p0, p1
    dx, dy = x2 - x1, y2 - y1
    length = hypot(dx, dy)
    radius = max(radius, length / 2)
    height = sqrt(max(radius * radius - (length / 2) ** 2, 0))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    for sign in (1, -1):
        cx, cy = mx + sign * height * -dy / length, my + sign * height * dx / length
        a1 = atan2(y1 - cy, x1 - cx)
        a2 = atan2(y2 - cy, x2 - cx)
        delta = (a2 - a1 + pi) % (2 * pi) - pi
        if (delta > 0) == bool(sweep):
            return [(cx + radius * cos(a1 + delta * i / n),
                     cy + radius * sin(a1 + delta * i / n))
                    for i in range(1, n + 1)]
    return [p1]


def _github_polygon():
    """The GitHub mark flattened to points in a 16x16 box (y down)."""
    global _GH_POLY
    if _GH_POLY:
        return _GH_POLY
    tokens = re.findall(r"[A-Za-z]|-?(?:\d*\.\d+|\d+)", GITHUB_PATH)
    points, index, command, current = [], 0, None, (0.0, 0.0)
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in "zZ":
                break
            continue
        if command == "M":
            current = (float(tokens[index]), float(tokens[index + 1]))
            points.append(current)
            index += 2
            command = "L"
        elif command in "Cc":
            values = [float(token) for token in tokens[index:index + 6]]
            index += 6
            if command == "c":
                values = [values[i] + current[i % 2] for i in range(6)]
            segment = _cubic(current, (values[0], values[1]),
                             (values[2], values[3]), (values[4], values[5]))
            points += segment
            current = segment[-1]
        elif command == "A":
            radius, sweep = float(tokens[index]), float(tokens[index + 4])
            end = (float(tokens[index + 5]), float(tokens[index + 6]))
            index += 7
            points += _arc(current, radius, sweep, end)
            current = end
        else:
            index += 1
    _GH_POLY = points
    return points


class UpdateIcon(Widget):
    """A small vector icon drawn with the canvas.

    It is not interactive, so a tap passes through to a parent clickable card.
    """

    kind = StringProperty("back")
    rgba = ListProperty(list(THEME.UPDATE_TEXT))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._draw, size=self._draw, kind=self._draw)
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        cx, cy = self.center
        size = min(self.width, self.height) / 2
        width = dp(1.6)
        kind = self.kind
        with self.canvas:
            if kind in ("download", "external", "shield"):
                Color(*THEME.UPDATE_ACCENT)
            elif kind == "github":
                Color(*THEME.UPDATE_MUTED)
            else:
                Color(*self.rgba)
            if kind == "back":
                Line(points=[cx + size * .8, cy, cx - size * .8, cy],
                     width=width)
                Line(points=[cx - size * .1, cy + size * .6, cx - size * .8,
                             cy, cx - size * .1, cy - size * .6], width=width)
            elif kind == "download":
                Line(points=[cx, cy + size * .8, cx, cy - size * .35],
                     width=width)
                Line(points=[cx - size * .45, cy - size * .05, cx,
                             cy - size * .5, cx + size * .45,
                             cy - size * .05], width=width)
                Line(points=[cx - size * .8, cy - size * .2, cx - size * .8,
                             cy - size * .8, cx + size * .8, cy - size * .8,
                             cx + size * .8, cy - size * .2], width=width)
            elif kind == "external":
                Line(points=[cx - size * .6, cy - size * .6, cx + size * .6,
                             cy + size * .6], width=width)
                Line(points=[cx - size * .1, cy + size * .6, cx + size * .6,
                             cy + size * .6, cx + size * .6, cy - size * .1],
                     width=width)
            elif kind == "shield":
                Line(points=[cx, cy + size, cx + size * .8, cy + size * .6,
                             cx + size * .8, cy - size * .1, cx, cy - size,
                             cx - size * .8, cy - size * .1, cx - size * .8,
                             cy + size * .6, cx, cy + size], width=width)
                Line(points=[cx - size * .35, cy, cx - size * .05,
                             cy - size * .3, cx + size * .4, cy + size * .3],
                     width=width)
            elif kind == "github":
                side = min(self.width, self.height)
                ox, oy, scale = cx - side / 2, cy + side / 2, side / 16.0
                tesselator = Tesselator()
                tesselator.add_contour([
                    value
                    for px, py in _github_polygon()
                    for value in (ox + px * scale, oy - py * scale)
                ])
                tesselator.tesselate(WINDING_ODD, TYPE_POLYGONS)
                for vertices, indices in tesselator.meshes:
                    Mesh(vertices=vertices, indices=indices,
                         mode="triangle_fan")


class UpdateIconButton(ButtonBehavior, UpdateIcon):
    """A tappable icon (the back button)."""


__all__ = (
    "AVATAR_TINTS",
    "UpdateAvatar",
    "UpdateCard",
    "UpdateChip",
    "UpdateClickableCard",
    "UpdateIcon",
    "UpdateIconButton",
    "UpdatePill",
)
