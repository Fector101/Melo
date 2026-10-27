"""The colours of the app.

They live here so that the KV rules and the widgets read the same values,
without the widgets having to reach for the running app.
"""

from kivy.utils import get_color_from_hex as hex_

#: The background of the app.
BG = hex_("#1c1f26")

#: The accent colour (the active track, the slider, the button).
ACCENT = hex_("#7cc4f5")

#: The colour of the primary text.
FG = [1, 1, 1, 1]

#: The colour of the secondary text.
FG_DIM = [.75, .77, .8, 1]

#: The colour of the glyph that stands in for a missing cover.
FG_GLYPH = [.60, .63, .68, 1]

#: The neutral tile behind the glyph.
TILE_BG = [.16, .17, .2, 1]
