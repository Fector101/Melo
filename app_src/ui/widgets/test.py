import os
import sys
import threading
import traceback
from datetime import datetime

# ---------------------------------------------------------------- config
CANDIDATE_DIRS = [
    "/storage/emulated/0",
]
LOG_FILENAME = "crash.log"


def _pick_log_dir():
    for d in CANDIDATE_DIRS:
        try:
            if d and os.path.isdir(d):
                test = os.path.join(d, ".w_test")
                with open(test, "w") as f:
                    f.write("ok")
                os.remove(test)
                return d
        except Exception:
            continue
    return "."


LOG_PATH = os.path.join(_pick_log_dir(), LOG_FILENAME)


# ---------------------------------------------------------------- writer
def _write(header, text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 70 + "\n")
            f.write(f"{header}\n")
            f.write(f"time: {datetime.now().isoformat()}\n")
            f.write("-" * 70 + "\n")
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception as e:
        print("crashlog write failed:", e, file=sys.stderr)


# ------------------------------------------------------- exception hooks
def _excepthook(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _write("UNCAUGHT EXCEPTION", text)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_excepthook(args):
    text = "".join(
        traceback.format_exception(args.exc_type, args.exc_value,
                                   args.exc_traceback)
    )
    _write(f"UNCAUGHT THREAD EXCEPTION (thread={args.thread.name})", text)
    threading.__excepthook__(args)


# ------------------------------------------------------- Kivy integration
def _install_kivy_handler():
    try:
        from kivy.base import ExceptionHandler, ExceptionManager
    except Exception:
        return

    class _FileExceptionHandler(ExceptionHandler):
        def handle_exception(self, inst):
            text = "".join(
                traceback.format_exception(type(inst), inst,
                                           inst.__traceback__)
            )
            _write("KIVY UNCAUGHT EXCEPTION", text)
            return True

    ExceptionManager.add_handler(_FileExceptionHandler())


# ------------------------------------------------------- public entry
_installed = False


def install():
    """Call once, as early as possible, before creating your App."""
    global _installed
    if _installed:
        return LOG_PATH

    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    _install_kivy_handler()

    try:
        from kivy.logger import Logger, LOG_LEVELS
        import logging
        Logger.setLevel(LOG_LEVELS["warning"])

        file_handler = logging.FileHandler(LOG_PATH, mode="a",
                                           encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        Logger.addHandler(file_handler)
        Logger.logfile = None
    except Exception:
        pass

    _installed = True
    return LOG_PATH


install()


# ================================================================= app
from kivy.app import App
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.utils import platform, get_color_from_hex as hex_
from kivy.core.window import Window
from kivy.properties import (StringProperty, ListProperty, BooleanProperty,
                             NumericProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.core.text import LabelBase
from kivy.clock import Clock
import base64
import tempfile

if platform not in ("android", "ios"):
    Window.size = (400, 860)

# ------------------------------------------------------- icon font
# Tiny embedded TTF (9 glyphs from Font Awesome Free 7, solid; icons are
# CC BY 4.0, https://fontawesome.com/license/free). It is written to a temp
# file at start-up so the app stays a single .py file.
ICON_FONT_B64 = (
    "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"
    "F/6ZFRYXLQLOLRcWAAIAAP4JA+gB9wAkAEkAAAExBwYGJyYmNTUhIgYGFRQGIyImNTQ+AjMh"
    "NTQ2NzYWFxcWFAExNzY2FxYWFRUhMjY2NTQ2MzIWFRQOAiMhFRQGBwYmJycmNAOXfQ0lEhEV"
    "/sdFckMlGRolOmeITgE5FBISJQ19EvyofQ0lEhEWAThFckMlGhklOmeITv7IFRISJQ19EgEM"
    "fQ0ICAcgEz5DckUaJCQaTohnOj8SIAcICA19EjT91X0NCAgHIBI/Q3JFGiUlGk6IZzo+EyAH"
    "CAgNfRI0AAEAAP5KAfQBtgATAAA3MQE2MhcWFAcBARYUBwYiJwEmNBIBdxI0ExIS/rUBSxIS"
    "EjQT/okSLAF3ExMSNBL+tf61EjQSExMBdxI0AAABAAH+iQLvAXcAHwAAEwEBNjIXFhQHAQEW"
    "FAcGIicBAQYiJyY0NwEBJjQ3NjJsAQwBDBI0ExIS/vMBDRISEjQT/vT+9BI0ExISAQ3+8xIS"
    "EjQBZf7zAQ0SEhI0E/70/vQSNBMSEgEN/vMSEhI0EwEMAQwSNBMSAAAAAAAABAA2AAEAAAAA"
    "AAEACAAAAAEAAAAAAAIABwAIAAMAAQQJAAEAEAAPAAMAAQQJAAIADgAfQXBwSWNvbnNSZWd1"
    "bGFyAEEAcABwAEkAYwBvAG4AcwBSAGUAZwB1AGwAYQByAAACAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAwAAAECAQMBBAEFAQYBBwEIAQkBCgELAQwGc2VhcmNoBHNvcnQIc2V0"
    "dGluZ3MEc3luYwRwcmV2BG5leHQFcGF1c2UEcGxheQZyZXBlYXQEYmFjawVjbG9zZQA="
)
GLYPHS = {
    "search": "\ue000", "sort": "\ue001", "settings": "\ue002",
    "sync": "\ue003", "prev": "\ue004", "next": "\ue005",
    "pause": "\ue006", "play": "\ue007", "repeat": "\ue008",
    "back": "\ue009", "close": "\ue00a",
}


def _write_icon_font():
    data = base64.b64decode("".join(ICON_FONT_B64))
    for d in (tempfile.gettempdir(), os.getcwd(), os.path.expanduser("~")):
        try:
            path = os.path.join(d, "app_icons.ttf")
            with open(path, "wb") as f:
                f.write(data)
            return path
        except Exception:
            continue
    raise RuntimeError("could not write icon font")


LabelBase.register(name="AppIcons", fn_regular=_write_icon_font())

KV = """
#:import dp kivy.metrics.dp
#:import NoTransition kivy.uix.screenmanager.NoTransition

<Icon>:
    size_hint: None, None
    size: dp(20), dp(20)
    font_name: "AppIcons"
    font_size: self.height
    halign: "center"
    valign: "middle"
    text_size: self.size

<Art>:
    size_hint: None, None
    size: dp(40), dp(40)
    canvas.before:
        Color:
            rgba: self.bg
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(6)]

<SongRow>:
    size_hint_y: None
    height: dp(70)
    padding: dp(15), dp(10), dp(15), dp(10)
    spacing: dp(16)
    Art:
        id: art
        pos_hint: {"center_y": .5}
        bg: root.art_color
        source: root.art
    BoxLayout:
        orientation: "vertical"
        padding: 0, dp(4)
        Label:
            text: root.title
            font_size: "15sp"
            color: root.fg
            halign: "left"
            valign: "bottom"
            text_size: self.size
            shorten: True
            shorten_from: "right"
        Label:
            text: root.artist
            font_size: "13sp"
            color: root.fg_dim
            halign: "left"
            valign: "top"
            text_size: self.size
            shorten: True
            shorten_from: "right"
    Label:
        text: root.duration
        font_size: "12sp"
        color: root.fg_dim
        size_hint_x: None
        width: dp(52)

<Fab>:
    size_hint: None, None
    size: dp(50), dp(50)
    canvas.before:
        Color:
            rgba: app.accent
        Ellipse:
            pos: self.pos
            size: self.size
    Icon:
        kind: "sync"
        color: 1, 1, 1, 1
        size: dp(26), dp(26)
        center: root.center

<IconButton>:
    size_hint: None, None
    size: dp(40), dp(40)
    pos_hint: {"center_y": .5}
    Icon:
        kind: root.kind
        color: root.icon_color
        size: dp(root.icon_size), dp(root.icon_size)
        center: root.center

<SearchBar>:
    canvas.before:
        Color:
            rgba: .165, .176, .2, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
    BoxLayout:
        size_hint: None, None
        size: self.minimum_width, dp(24)
        spacing: dp(8)
        pos_hint: {"center_x": .5, "center_y": .5}
        Icon:
            kind: "search"
            size: dp(20), dp(20)
            pos_hint: {"center_y": .5}
        Label:
            text: "Search your library"
            font_size: "15sp"
            size_hint_x: None
            width: self.texture_size[0]

<SortButton>:
    size_hint_x: None
    width: dp(52)
    canvas.before:
        Color:
            rgba: .165, .176, .2, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
    Icon:
        kind: "sort"
        size: dp(22), dp(22)
        center: root.center

<PlayAllButton>:
    size_hint: None, None
    size: dp(104), dp(36)
    canvas.before:
        Color:
            rgba: .165, .176, .2, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(18)]
    BoxLayout:
        size_hint: None, None
        size: self.minimum_width, dp(20)
        spacing: dp(6)
        pos_hint: {"center_x": .5, "center_y": .5}
        Icon:
            kind: "play"
            color: app.accent
            size: dp(14), dp(14)
            pos_hint: {"center_y": .5}
        Label:
            text: "Play all"
            font_size: "14sp"
            color: app.accent
            size_hint_x: None
            width: self.texture_size[0]

<Player>:
    orientation: "vertical"
    size_hint_y: None
    height: dp(175)
    padding: dp(14), dp(10), dp(14), dp(10)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: .09, .09, .1, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        spacing: dp(14)
        Art:
            bg: root.art_color
            source: root.art
        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: dp(30)
            spacing: dp(2)
            Label:
                text: root.title
                font_size: "15sp"
                halign: "left"
                valign: "bottom"
                text_size: self.size
            Label:
                text: root.artist
                font_size: "13sp"
                color: .75, .77, .8, 1
                halign: "left"
                valign: "top"
                text_size: self.size
    FloatLayout:
        size_hint_y: None
        height: dp(44)
        BoxLayout:
            size_hint: None, None
            width: self.minimum_width
            height: dp(20)
            spacing: dp(30)
            pos_hint: {"center_x": .5, "center_y": .35}
            Icon:
                kind: "prev"
            Icon:
                kind: "play" if not root.playing else "pause"
            Icon:
                kind: "next"
        Icon:
            kind: "repeat"
            size: dp(22), dp(22)
            pos_hint: {"right": .97, "center_y": .35}
    BoxLayout:
        orientation: "vertical"
        FillSlider:
            min: 0
            max: root.total
            value: root.position
            value_track: True
            value_track_color: app.accent
            value_track_width: dp(2)
            cursor_size: 0, 0
            padding: dp(8)
            on_value: root.position = self.value
        BoxLayout:
            size_hint_y: None
            height: dp(18)
            padding: dp(8), 0
            Label:
                text: root.fmt(root.position)
                font_size: "13sp"
                color: .6, .62, .66, 1
                halign: "left"
                text_size: self.size
            Label:
                text: root.fmt(root.total)
                font_size: "13sp"
                color: .6, .62, .66, 1
                halign: "right"
                text_size: self.size

<Library>:
    canvas.before:
        Color:
            rgba: app.bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: "vertical"
        ScreenManager:
            id: sm
            transition: NoTransition()
            Screen:
                name: "library"
                BoxLayout:
                    orientation: "vertical"
                    BoxLayout:
                        orientation: "vertical"
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(12), dp(35), dp(28), dp(14)
                        spacing: dp(10)
                        BoxLayout:
                            size_hint_y: None
                            height: dp(52)
                            Label:
                                text: "Your Library"
                                bold: True
                                font_size: "34sp"
                                halign: "left"
                                valign: "middle"
                                text_size: self.size
                            IconButton:
                                kind: "settings"
                                width: dp(52)
                                on_release: app.open_settings()
                        Label:
                            id: count
                            font_size: "16sp"
                            size_hint_y: None
                            height: dp(24)
                            halign: "left"
                            valign: "middle"
                            text_size: self.size
                            padding: dp(11), 0
                        BoxLayout:
                            size_hint_y: None
                            height: dp(48)
                            spacing: dp(12)
                            SearchBar:
                                on_release: app.open_search()
                            SortButton:
                                on_release: app.sort_songs()
                    ScrollView:
                        bar_width: 0
                        GridLayout:
                            id: songs
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height
                Fab:
                    pos: root.width - self.width - dp(30), dp(24)
                    on_release: app.add_song()
            Screen:
                name: "search"
                BoxLayout:
                    orientation: "vertical"
                    BoxLayout:
                        orientation: "vertical"
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(10), dp(40), dp(20), dp(8)
                        BoxLayout:
                            size_hint_y: None
                            height: dp(50)
                            spacing: dp(8)
                            IconButton:
                                kind: "back"
                                icon_size: 22
                                on_release: app.close_search()
                            BoxLayout:
                                padding: dp(14), 0, dp(2), 0
                                spacing: dp(10)
                                canvas.before:
                                    Color:
                                        rgba: .165, .176, .2, 1
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(12)]
                                Icon:
                                    kind: "search"
                                    color: .62, .65, .7, 1
                                    pos_hint: {"center_y": .5}
                                TextInput:
                                    id: search_input
                                    hint_text: "Search songs or artists"
                                    multiline: False
                                    background_normal: ""
                                    background_active: ""
                                    background_color: 0, 0, 0, 0
                                    foreground_color: 1, 1, 1, 1
                                    hint_text_color: .62, .65, .7, 1
                                    cursor_color: app.accent
                                    font_size: "16sp"
                                    padding: [0, max(0, (self.height - self.line_height) / 2), 0, 0]
                                    on_text: app.filter_songs(self.text)
                                IconButton:
                                    kind: "close"
                                    icon_size: 14
                                    icon_color: .62, .65, .7, 1
                                    opacity: 1 if search_input.text else 0
                                    disabled: not search_input.text
                                    on_release: search_input.text = ""
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        padding: dp(18), 0, dp(20), 0
                        spacing: dp(12)
                        Label:
                            id: result_count
                            font_size: "14sp"
                            color: .62, .65, .7, 1
                            size_hint_x: None
                            width: self.texture_size[0]
                        PlayAllButton:
                            pos_hint: {"center_y": .5}
                            on_release: app.play_all()
                        Widget:
                    ScrollView:
                        bar_width: 0
                        GridLayout:
                            id: results
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height
        Player:
            id: player
"""


class FillSlider(Slider):
    """Slider with a darker custom track and a filled accent-colour thumb."""

    def __init__(self, **kw):
        kw.setdefault("background_width", 0)   # hides the default grey track
        super().__init__(**kw)
        from kivy.graphics import Color, RoundedRectangle, Ellipse
        with self.canvas.before:
            Color(.22, .24, .28, 1)          # track colour (lower = darker)
            self._track = RoundedRectangle(radius=[dp(1)])
        with self.canvas.after:
            Color(*App.get_running_app().accent)
            self._thumb = Ellipse(size=(dp(18), dp(18)))
        self.bind(pos=self._upd, size=self._upd,
                  value_pos=self._upd, padding=self._upd)
        self._upd()

    def _upd(self, *_):
        pad = self.padding
        self._track.pos = (self.x + pad, self.center_y - dp(1))
        self._track.size = (self.width - 2 * pad, dp(2))
        self._thumb.pos = (self.value_pos[0] - dp(9), self.center_y - dp(9))


class Icon(Label):
    """Font-based icon. Set `kind` (see GLYPHS); colour via `color`."""
    kind = StringProperty("play")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.text = GLYPHS.get(self.kind, "")

    def on_kind(self, *_):
        self.text = GLYPHS.get(self.kind, "")


class Art(FloatLayout):
    bg = ListProperty([.3, .3, .3, 1])
    source = StringProperty("")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(source=self._load)
        self._load()

    def _load(self, *_):
        self.clear_widgets()
        if self.source and os.path.exists(self.source):
            self.add_widget(Image(source=self.source, allow_stretch=True,
                                  keep_ratio=False,
                                  size_hint=(1, 1),
                                  pos_hint={"x": 0, "y": 0}))


class Fab(ButtonBehavior, FloatLayout):
    pass


class IconButton(ButtonBehavior, FloatLayout):
    kind = StringProperty("search")
    icon_color = ListProperty([1, 1, 1, 1])
    icon_size = NumericProperty(24)          # in dp


class PlayAllButton(ButtonBehavior, FloatLayout):
    pass


class SearchBar(ButtonBehavior, FloatLayout):
    pass


class SortButton(ButtonBehavior, FloatLayout):
    pass


class SongRow(ButtonBehavior, BoxLayout):
    title = StringProperty()
    artist = StringProperty()
    duration = StringProperty("2:03")
    art = StringProperty("")
    art_color = ListProperty([.3, .3, .3, 1])
    active = BooleanProperty(False)
    fg = ListProperty([1, 1, 1, 1])
    fg_dim = ListProperty([.75, .77, .8, 1])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(active=self._style)
        self._style()

    def _style(self, *_):
        blue = App.get_running_app().accent
        if self.active:
            self.fg, self.fg_dim = blue, blue
        else:
            self.fg, self.fg_dim = [1, 1, 1, 1], [.75, .77, .8, 1]


class Player(BoxLayout):
    title = StringProperty("yellow brick road")
    artist = StringProperty("Eminem")
    art = StringProperty("")
    art_color = ListProperty(hex_("#c0392b"))
    playing = BooleanProperty(True)
    position = NumericProperty(105)  # seconds
    total = NumericProperty(252)

    @staticmethod
    def fmt(sec):
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"


class Library(FloatLayout):
    pass


SONGS = [
    ("the song they played", "Lil peep", "2:03", "#c0392b", True),
    ("Fortunate Son", "Creedence Clearwater Revival", "3:34", "#6b6a5a", False),
    ("Harlem Streets", "immortal technique", "4:01", "#cfcfcf", False),
    ("The Wedding List", "Kate Bush", "1:09", "#5c5648", False),
]


class MusicApp(App):
    bg = ListProperty(hex_("#1c1f26"))
    accent = ListProperty(hex_("#7cc4f5"))

    def build(self):
        Window.clearcolor = self.bg
        Builder.load_string(KV)
        self.root_ui = Library()
        self.song_count = 20
        self.current_key = next(((t, a) for t, a, _, _, on in SONGS if on),
                                None)
        self._matches = list(SONGS)
        grid = self.root_ui.ids.songs
        for song in SONGS:
            grid.add_widget(self._make_row(song))
        self._update_count()
        Window.bind(on_keyboard=self._on_key)
        return self.root_ui

    # ---------------------------------------------------------- helpers
    def _make_row(self, song):
        title, artist, dur, color, _ = song
        return SongRow(title=title, artist=artist, duration=dur,
                       art_color=hex_(color),
                       active=(title, artist) == self.current_key,
                       on_release=self.play)

    def _update_count(self):
        self.root_ui.ids.count.text = f"{self.song_count} songs added"

    def _on_key(self, window, key, *args):
        # Android back button / Esc closes the search screen
        if key == 27 and self.root_ui.ids.sm.current == "search":
            self.close_search()
            return True
        return False

    # ---------------------------------------------------------- playback
    def _play(self, title, artist, art_color, art=""):
        p = self.root_ui.ids.player
        p.title, p.artist = title, artist
        p.art_color, p.art = art_color, art
        p.position, p.playing = 0, True
        self.current_key = (title, artist)
        for grid in (self.root_ui.ids.songs, self.root_ui.ids.results):
            for r in grid.children:
                r.active = (r.title, r.artist) == self.current_key

    def play(self, row):
        self._play(row.title, row.artist, row.art_color, row.art)

    def play_all(self):
        if self._matches:
            title, artist, _, color, _ = self._matches[0]
            self._play(title, artist, hex_(color))

    # ---------------------------------------------------------- library
    def add_song(self):
        # placeholder: replace with your real sync logic
        self.song_count += 1
        self._update_count()

    def sort_songs(self):
        # toggles A-Z / Z-A by title; change the key to sort by artist etc.
        self.sort_asc = not getattr(self, "sort_asc", False)
        grid = self.root_ui.ids.songs
        rows = sorted(grid.children[:], key=lambda r: r.title.lower(),
                      reverse=not self.sort_asc)
        grid.clear_widgets()
        for r in rows:
            grid.add_widget(r)

    def open_settings(self):
        # placeholder: open your settings screen here
        print("settings pressed")

    # ---------------------------------------------------------- search
    def open_search(self):
        ids = self.root_ui.ids
        ids.sm.current = "search"
        ids.search_input.text = ""
        self.filter_songs("")
        Clock.schedule_once(
            lambda dt: setattr(ids.search_input, "focus", True), .15)

    def close_search(self):
        ids = self.root_ui.ids
        ids.search_input.focus = False
        ids.sm.current = "library"

    def filter_songs(self, text):
        q = (text or "").strip().lower()
        self._matches = [s for s in SONGS
                         if q in s[0].lower() or q in s[1].lower()]
        ids = self.root_ui.ids
        grid = ids.results
        grid.clear_widgets()
        for song in self._matches:
            grid.add_widget(self._make_row(song))
        if not self._matches:
            grid.add_widget(Label(text="No songs match your search",
                                  size_hint_y=None, height=dp(80),
                                  color=(.62, .65, .7, 1)))
        n = len(self._matches)
        ids.result_count.text = f"{n} song{'' if n == 1 else 's'}"


if __name__ == "__main__":
    MusicApp().run()