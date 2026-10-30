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

# --------------------------------------------------------------------------- #
# The update screen                                                           #
# --------------------------------------------------------------------------- #
# The palette of the update screen, kept apart from the library so the
# lazy-loaded screen reads the same values from both Python and KV.
UPDATE_BG = [.11, .12, .15, 1]
UPDATE_ACCENT = [.36, .72, .94, 1]
UPDATE_TEXT = [.91, .92, .94, 1]
UPDATE_MUTED = [.66, .68, .72, 1]
UPDATE_LINE = [.22, .24, .28, 1]
UPDATE_CARD_BG = [.14, .15, .18, 1]
UPDATE_ROW_BG = [.12, .13, .16, 1]
UPDATE_HIGHLIGHT = [.78, .80, .84, 1]
UPDATE_DANGER = [.95, .45, .40, 1]
UPDATE_OK = [.30, .78, .45, 1]
UPDATE_BUTTON_TEXT = [.05, .10, .15, 1]
UPDATE_ACCENT_DIM = [.36, .72, .94, .35]
UPDATE_BUTTON_TEXT_DIM = [.05, .10, .15, .7]
