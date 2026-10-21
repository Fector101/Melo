"""
Music player: library UI + plain-controller playback with media notification
===========================================================================

Single-file app that merges the library player UI with a working playback
backend: MediaStore scan, tap-to-play, draggable seek bar, loop-one toggle,
auto-advance at track end, and a media notification / lock screen / headset
transport.

Playback is Kivy's own ``SoundLoader`` wrapped in a plain object
(``KivySoundController``). Because that controller has no ``bind`` / ``events``,
``MediaNotification`` cannot subscribe to playback state and is instead fed by
hand: **every app-driven change calls ``notification.syncPlaybackState()``**.
The notification's own play / pause / seek / next / prev buttons still come back
into the controller (their state lands in the UI on the next ticker pass).

Consequences of using Kivy's ``SoundLoader``:

- It plays *file paths* only, so tracks are resolved from MediaStore ``_data``
  instead of ``content://`` URIs. ``_data`` is filtered on Android 10+ unless the
  app holds All Files Access, so this scan is really aimed at older Android or
  testing.
- There is no ``on_complete`` event, so auto-advance is guessed from position in
  the app-side UI ticker (``get_pos()`` at the track length, or a rewind while
  playing). That is app-side refresh only - the notification is never polled.
"""

import logging
import os
import threading
import time
import traceback
import zlib

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget
from kivy.utils import platform, get_color_from_hex as hex_

try:
    from kivy.core.audio_output import SoundLoader as KivySoundLoader
except ModuleNotFoundError:
    from kivy.core.audio import SoundLoader as KivySoundLoader

from android_notify import logger as android_notify_logger
from android_notify.config import (on_android_platform,
                                   get_python_activity_context)
from android_notify.internal.permissions import is_music_permission_in_manifest
from android_notify.media import MediaNotification
from android_notify.media.music.helper import MediaPermissionHandler

android_notify_logger.setLevel(logging.DEBUG)
logger = logging.getLogger("melo")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

if platform not in ("android", "ios"):
    Window.size = (400, 860)

if on_android_platform():
    try:
        from jnius import autoclass, PythonJavaClass, java_method
    except Exception:
        autoclass = None
        PythonJavaClass = None
        java_method = None
    if autoclass is not None:
        MediaMetadataRetriever = autoclass("android.media.MediaMetadataRetriever")
    else:
        MediaMetadataRetriever = None
else:
    autoclass = None
    PythonJavaClass = None
    java_method = None
    MediaMetadataRetriever = None

if on_android_platform() and PythonJavaClass is not None:

    class _AndroidUIRunnable(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        def __init__(self, fn):
            super().__init__()
            self.fn = fn

        @java_method("()V")
        def run(self):
            try:
                self.fn()
            except Exception:
                traceback.print_exc()
else:
    _AndroidUIRunnable = None

# --------------------------------------------------------------------------- #
# System-bar insets                                                            #
# --------------------------------------------------------------------------- #
# Android 15 (targetSdk 35+) enforces edge-to-edge: the window always draws
# behind the status bar and the nav buttons, and no manifest option can reserve
# space for them - buildozer's android.display_cutout only concerns the notch
# and is overridden to `always` by the system anyway (verified via dumpsys).
# So the root widget pads itself with the real window insets instead, refreshed
# whenever the system reports a change (e.g.3-button <-> gesture navigation).

_insets_listener = None  # JNI objects held at module level so the GC leaves
_insets_register = None  # them alone for the lifetime of the process


def _read_insets(insets):
    """WindowInsets -> status/nav/cutout insets in **physical pixels**.

    Kivy lays out in pixels on Android, so the raw values slot straight into
    KV positions/sizes. ``getInsetsIgnoringVisibility`` keeps the padding
    stable while a bar is temporarily hidden (immersive swipe, keyboard).
    """
    if autoclass("android.os.Build$VERSION").SDK_INT >= 30:
        inset_type = autoclass("android.view.WindowInsets$Type")
        bars = inset_type.statusBars() | inset_type.navigationBars()
        system = insets.getInsetsIgnoringVisibility(bars)
        top, bottom = system.top, system.bottom
        left, right = system.left, system.right
    else:  # API 28/29: WindowInsets.Type does not exist yet
        top, bottom = insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetBottom()
        left, right = insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetRight()
    try:
        cutout = insets.getDisplayCutout()  # API 28+; None when there is none
        if cutout is not None:
            top = max(top, cutout.getSafeInsetTop())
            bottom = max(bottom, cutout.getSafeInsetBottom())
            left = max(left, cutout.getSafeInsetLeft())
            right = max(right, cutout.getSafeInsetRight())
    except Exception as error:
        logger.debug("no display-cutout insets: %s", error)
    return {"top": top, "bottom": bottom, "left": left, "right": right}


def _resource_inset_px(dimen_name):
    """Fallback px inset from an Android resource (before the callback fires)."""
    try:
        resources = get_python_activity_context().getResources()
        res_id = resources.getIdentifier(dimen_name, "dimen", "android")
        return int(resources.getDimensionPixelSize(res_id)) if res_id else 0
    except Exception as error:
        logger.debug("%s resource unavailable: %s", dimen_name, error)
        return 0


def _fallback_insets():
    return {"top": _resource_inset_px("status_bar_height"),
            "bottom": _resource_inset_px("navigation_bar_height"),
            "left": 0, "right": 0}


def _apply_insets(root, insets):
    """Push insets onto the Kivy root from whichever thread reported them."""

    def _set(_dt):
        root.inset_top = insets["top"]
        root.inset_bottom = insets["bottom"]
        root.inset_left = insets["left"]
        root.inset_right = insets["right"]

    Clock.schedule_once(_set, 0)  # Kivy properties change on Kivy's own thread


if on_android_platform():
    class _InsetsListener(PythonJavaClass):
        __javainterfaces__ = ["android/view/View$OnApplyWindowInsetsListener"]
        __javacontext__ = "app"

        def __init__(self, apply_insets):
            super().__init__()
            self._apply_insets = apply_insets

        @java_method("(Landroid/view/View;Landroid/view/WindowInsets;)Landroid/view/WindowInsets;")
        def onApplyWindowInsets(self, view, insets):
            try:
                self._apply_insets(_read_insets(insets))
            except Exception as error:
                logger.warning("window-insets callback failed: %s", error)
            return insets  # un-consumed: SDL's own listener must keep seeing them


    class _RegisterInsetsRunnable(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        def __init__(self, decor, listener):
            super().__init__()
            self._decor = decor
            self._listener = listener

        @java_method("()V")
        def run(self):
            # Set on the decor view: SDL listens on SDLSurface instead, so the
            # two listeners do not overwrite each other.
            self._decor.setOnApplyWindowInsetsListener(self._listener)
            self._decor.requestApplyInsets()


def _start_insets_updates(root):
    """Keep ``root``'s inset properties in sync with the real system bars.

    No-op off Android. Falls back to Android's dimension resources so the
    layout never starts out overlapping the bars if the callback is delayed;
    the callback then corrects the values as soon as the view is attached.
    """
    global _insets_listener, _insets_register
    if not on_android_platform():
        return
    try:
        activity = get_python_activity_context()
        decor = activity.getWindow().getDecorView()

        listener = _InsetsListener(lambda insets: _apply_insets(root, insets))
        register = _RegisterInsetsRunnable(decor, listener)
        _insets_listener, _insets_register = listener, register
        activity.runOnUiThread(register)

        current = decor.getRootWindowInsets()
        if current is not None:
            _apply_insets(root, _read_insets(current))
        else:  # not attached yet: requestApplyInsets() above follows up
            _apply_insets(root, _fallback_insets())
    except Exception as error:
        logger.warning("system-bar inset setup failed: %s", error)
        _apply_insets(root, _fallback_insets())


def _basename(path):
    """Best-effort human name for a file path."""
    name = path.rstrip("/")
    return os.path.basename(name) or name


# --------------------------------------------------------------------------- #
# Cover art: embedded picture -> cached file. ``MediaMetadataRetriever`` is     #
# JVM + I/O work, so only the background art worker may call these helpers.    #
# --------------------------------------------------------------------------- #
_art_cache = {}  # track path -> cached art file path ("" when there is none)
_art_dir = None
_art_failed_extensions = set()  # logged once per file type, not per file


def _art_cache_dir():
    """Writable directory for cached cover art, created on first use."""
    global _art_dir
    if _art_dir is None:
        app = App.get_running_app()
        base = (app.user_data_dir if app is not None
                else os.environ.get("ANDROID_PRIVATE", ""))
        _art_dir = os.path.join(base, "art_cache") if base else ""
        if _art_dir:
            try:
                os.makedirs(_art_dir, exist_ok=True)
            except OSError as error:
                logger.warning("no art cache dir (%s): %s", _art_dir, error)
                _art_dir = ""
    return _art_dir


def embedded_art_path(track_path):
    """Cached path to a track's embedded cover, or '' when it has none.

    The result is memoised and the bytes are written once to ``art_cache``, so
    each file is decoded at most once per install. Never call this on the UI
    thread - extracting from a large file can take tens of milliseconds.
    """
    key = str(track_path)
    if key in _art_cache:
        return _art_cache[key]

    result = ""
    directory = _art_cache_dir() if MediaMetadataRetriever is not None else ""
    if directory:
        stem = os.path.join(directory,
                            f"{zlib.crc32(key.encode('utf-8')):08x}")
        for extension in (".jpg", ".png"):  # reused from an earlier run
            if os.path.exists(stem + extension):
                result = stem + extension
                break
        else:
            retriever = None
            try:
                retriever = MediaMetadataRetriever()
                retriever.setDataSource(key)
                art = retriever.getEmbeddedPicture()
                if art:
                    data = bytes(art)
                    target = stem + (".png" if data[:8] == b"\x89PNG\r\n\x1a\n"
                                     else ".jpg")
                    with open(target, "wb") as handle:
                        handle.write(data)
                    result = target
            except Exception as error:
                # pyjnius builds a multi-line message (class, text and every
                # Java frame), which logcat prints as a wall of stack. Keep it
                # to one line, and only once per file type.
                extension = os.path.splitext(key)[1].lower() or "<none>"
                if extension not in _art_failed_extensions:
                    _art_failed_extensions.add(extension)
                    reason = str(error).splitlines()[0] if str(error) else error
                    logger.debug("no embedded art for %s files: %s",
                                 extension, reason)
            finally:
                if retriever is not None:
                    try:
                        retriever.release()
                    except Exception:
                        pass
    _art_cache[key] = result
    return result


def scan_audio_file_paths():
    """MediaStore -> list of audio file paths (the ``_data`` column).

    Kivy's SoundLoader plays paths, not ``content://`` URIs. ``_data`` is
    filtered on Android 10+ unless the app holds All Files Access, so this is
    primarily for Android 9 and below / testing.
    """
    if not on_android_platform():
        return []

    context = get_python_activity_context()
    if not context:
        logger.error("scan_audio_file_paths: no activity context")
        return []

    resolver = context.getContentResolver()
    uri = autoclass("android.provider.MediaStore$Audio$Media").EXTERNAL_CONTENT_URI
    projection = ["_id", "title", "artist", "duration", "_data"]
    cursor = resolver.query(uri, projection, None, None, None)
    tracks = []

    if cursor:
        title_idx = cursor.getColumnIndex("title")
        artist_idx = cursor.getColumnIndex("artist")
        duration_idx = cursor.getColumnIndex("duration")
        data_idx = cursor.getColumnIndex("_data")
        while cursor.moveToNext():
            path = cursor.getString(data_idx)
            if not path:
                continue
            tracks.append(
                {
                    "path": path,
                    "title": cursor.getString(title_idx) or "(unknown title)",
                    "artist": cursor.getString(artist_idx) or "",
                    "duration": cursor.getLong(duration_idx),
                }
            )
        cursor.close()
    tracks.sort(key=lambda track: track["title"].lower())
    logger.info("Scan complete: %d loadable file path(s)", len(tracks))
    return tracks


def _load_kivy_sound(path):
    """Load ``path`` through an audio provider that outlives the activity.

    Kivy's provider priority (``PROVIDER_CONFIGS['audio_output']``) is
    ``gstplayer, ffpyplayer, sdl3, avplayer, android``, and ``fallback_load()``
    takes the first one that supports the extension. With the sdl3 bootstrap
    that means SDL owns playback, and SDL suspends its Android audio device as
    soon as the activity pauses - which happens both when the app is left and
    when the screen turns off. The ``android`` provider is a framework
    ``MediaPlayer`` that keeps playing in the background, so ask for it
    explicitly. Kivy falls back to its default order on its own if the provider
    is unavailable or fails to load the file, and desktop just uses the default.
    """
    if on_android_platform():
        return KivySoundLoader.load(path, audio_output_provider="android")
    return KivySoundLoader.load(path)


def _keep_cpu_awake(sound):
    """Let the framework player keep decoding while the screen is off.

    ``MediaPlayer`` does not hold a wake lock by itself; without one a deep
    sleep can stall playback. Best-effort only - desktop sounds have no player.
    """
    player = getattr(sound, "_mediaplayer", None)
    if player is None:
        return
    try:
        power = autoclass("android.os.PowerManager")
        player.setWakeMode(
            get_python_activity_context(), power.PARTIAL_WAKE_LOCK)
    except Exception as error:
        logger.debug("setWakeMode unavailable: %s", error)


class KivySoundController:
    """Minimal ``IMediaController`` adapter around a Kivy ``Sound`` (no events).

    A plain object on purpose: it has no ``bind`` / ``dispatch`` / ``events``,
    so ``MediaNotification`` treats it as a controller that cannot drive the
    notification through events - the app must call ``syncPlaybackState()``.

    One instance is reused for every track via :meth:`load`, so the
    ``MediaNotification`` built around it stays valid across track changes.
    """

    def __init__(self):
        self._sound = None
        self._length = 0.0
        self._pos = 0.0
        self._playing = False
        self._paused = False
        self._loop = False
        self._user_stopped = False
        self._on_track_end = None

    def set_on_track_end(self, callback):
        self._on_track_end = callback

    def load(self, path):
        """Drop the current sound and load a new one. Returns True on success."""
        self.stop_playback()
        self._sound = _load_kivy_sound(path)
        self._length = float(self._sound.length or 0) if self._sound else 0.0
        self._pos = 0.0
        if self._sound is not None:
            try:
                self._sound.bind(on_stop=self._on_sound_stopped)
            except Exception:
                pass
            self._sound.loop = self._loop
            _keep_cpu_awake(self._sound)
        self._user_stopped = False
        return self._sound is not None

    def _on_sound_stopped(self, *args):
        logger.debug("sound stopped: user_stopped=%s, has_cb=%s", self._user_stopped, self._on_track_end is not None)
        if self._user_stopped:
            return
        cb = self._on_track_end
        if cb is None:
            return
        try:
            length = self.get_length()
            pos = self.get_pos()
            logger.debug("end check: length=%.2f pos=%.2f diff=%.3f", length, pos, (length - pos) if length > 0 else -1)
            if length > 1.0 and pos >= length - 0.25:
                logger.info("native completion detected -> advancing")
                try:
                    activity = get_python_activity_context()
                    if activity is not None and _AndroidUIRunnable is not None:
                        activity.runOnUiThread(_AndroidUIRunnable(cb))
                        return
                except Exception:
                    pass
                try:
                    cb()
                except Exception as e:
                    logger.debug("end cb failed: %s", e)
                return
        except Exception as error:
            logger.debug("sound stopped end check failed: %s", error)
            traceback.print_exc()

    def stop_playback(self):
        self._user_stopped = True
        if self._sound is not None:
            try:
                try:
                    self._sound.unbind(on_stop=self._on_sound_stopped)
                except Exception:
                    pass
                self._sound.stop()
                self._sound.unload()
            except Exception as error:
                logger.warning("sound cleanup error: %s", error)
            self._sound = None
        self._pos = 0.0
        self._playing = False
        self._paused = False

    # --- IMediaController contract -----------------------------------------
    @property
    def source(self):
        return self._sound.source if self._sound else None

    @property
    def length(self):
        return self._length

    @property
    def state(self):
        if self._paused:
            return "pause"
        return "play" if self._playing else "stop"

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value):
        self._loop = bool(value)
        if self._sound is not None:
            self._sound.loop = self._loop

    def play(self):
        if self._sound is None:
            return
        self._user_stopped = False
        self._sound.play()
        if self._paused:
            # Kivy's Sound cannot resume in place, so seek back after starting.
            self._sound.seek(self._pos)
        self._paused = False
        self._playing = True

    def pause(self):
        if self._sound is None:
            return
        self._user_stopped = True
        self._pos = self.get_pos()
        self._sound.stop()  # Kivy Sound has no pause(); stop and remember.
        self._paused = True
        self._playing = False

    def seek(self, seconds):
        if self._sound is None:
            return
        self._pos = float(max(0.0, seconds))
        self._sound.seek(self._pos)

    def get_pos(self):
        if self._sound is None:
            return 0.0
        if self._paused:
            return self._pos
        pos = self._sound.get_pos()
        if pos is not None:
            self._pos = float(pos)
        return self._pos

    def get_length(self):
        """Length may only be known after the sound is loaded (no on_load event)."""
        if self._sound is not None and self._sound.length:
            self._length = float(self._sound.length)
        return self._length


KV = """
#:import dp kivy.metrics.dp

<Icon>:
    size_hint: None, None
    size: dp(16), dp(16)

<TransportIcon>:
    size_hint: None, None
    size: dp(16), dp(16)

<Art>:
    size_hint: None, None
    size: dp(40), dp(40)
    canvas.before:
        # Clip everything the widget draws (the tile + cover Image child) to a
        # rounded rect, so real art gets the same rounded corners.
        StencilPush
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(6)]
        StencilUse
        Color:
            rgba: self.bg
        Rectangle:
            pos: self.pos
            size: self.size
    canvas.after:
        StencilUnUse
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(6)]
        StencilPop
    Icon:
        id: glyph
        kind: "note"
        size: dp(20), dp(20)
        center: root.center
        color: .60, .63, .68, 1
        # The cover Image, when there is one, hides the fallback note.
        opacity: 0 if root.art_loaded else 1

<SongRow>:
    size_hint_y: None
    height: dp(70)
    padding: dp(15), dp(10), dp(15), dp(10)
    spacing: dp(16)
    Art:
        id: art
        pos_hint: {"center_y": .5}
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
        size: dp(24), dp(24)
        center: root.center

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
            source: root.art
        BoxLayout:
            id:p
            orientation: "vertical"
            size_hint_y: None
            height: dp(30)
            spacing: dp(2)
            # canvas.before:
            #     Color:
            #         rgba: .09, 1, .1, 1
            #     Rectangle:
            #         pos: self.pos
            #         size: self.size

            Label:
                text: root.title
                font_size: "15sp"
                halign: "left"
                valign: "bottom"
                text_size: self.size
                shorten: True
                shorten_from: 'center'

            Label:
                text: root.artist
                font_size: "13sp"
                color: .75, .77, .8, 1
                halign: "left"
                valign: "top"
                size_hint: [None,None]
                size: self.texture_size
                shorten_from: 'right'
                shorten:True

    FloatLayout:
        size_hint_y: None
        height: dp(44)
        BoxLayout:
            size_hint: None, None
            width: self.minimum_width
            height: dp(16)
            spacing: dp(30)
            pos_hint: {"center_x": .5, "center_y": .35}
            TransportIcon:
                kind: "prev"
                on_release: app.previous_track()
            TransportIcon:
                kind: "play" if not root.playing else "pause"
                size: dp(16), dp(20)
                pos_hint: {"center_y": .49}
                on_release: app.toggle_play_pause()
            TransportIcon:
                kind: "next"
                on_release: app.next_track()
        TransportIcon:
            kind: "repeat"
            size: dp(25), dp(25)
            color: app.accent if root.loop_on else (1, 1, 1, 1)
            pos_hint: {"right": .97, "center_y": .35}
            on_release: app.toggle_loop()
    BoxLayout:
        orientation: "vertical"
        FillSlider:
            id: seek
            min: 0
            max: root.total
            value: root.position
            value_track: True
            value_track_color: app.accent
            value_track_width: dp(2)
            # cursor_size: dp(15), dp(15)
            # background_width: dp(20)
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
        size_hint: None, None
        pos: root.x + root.inset_left, root.y + root.inset_bottom
        size: root.width - root.inset_left - root.inset_right, root.height - root.inset_top - root.inset_bottom
        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
            padding: dp(15), dp(30), dp(15), dp(10)
            spacing: dp(15)
            Label:
                text: "Your Library"
                bold: True
                font_size: "40sp"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Label:
                id: count
                font_size: "18sp"
                size_hint_y: None
                height: dp(34)
                halign: "left"
                valign: "middle"
                text_size: self.size
                padding: dp(10), 0
        RecycleView:
            id: songs
            viewclass: "SongRow"
            RecycleBoxLayout:
                orientation: "vertical"
                default_size: None, dp(70)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
        Player:
            id: player
    Fab:
        id: fab
        right: root.right - root.inset_right - dp(30)
        y: root.y + root.inset_bottom + player.height + dp(24)
        on_release: app.scan_device()
"""


class FillSlider(Slider):
    """Slider that reports a user drag, so the ticker keeps its hands off.

    ``seeking`` is True between touch-down and touch-up; on release the app is
    asked to seek. Playback position updates are skipped while it is set, which
    stops the 0.25s ticker from fighting the finger.
    """

    seeking = BooleanProperty(False)

    def __init__(self, **kw):
        kw.setdefault("background_width", 0)   # hides the default grey track
        super().__init__(**kw)
        from kivy.graphics import Color, RoundedRectangle, Ellipse
        with self.canvas.before:
            Color(.22, .24, .28, 1)          # track colour (lower = darker)
            self._track = RoundedRectangle(radius=[dp(1.7)])
        with self.canvas.after:
            Color(*App.get_running_app().accent)
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
            app = App.get_running_app()
            if app is not None:
                app.perform_seek(self.value)
        return super().on_touch_up(touch)


class Icon(Widget):
    kind = StringProperty("play")
    color = ListProperty([1, 1, 1, 1])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self.draw, size=self.draw, kind=self.draw,
                  color=self.draw)
        self.draw()

    def draw(self, *_):
        from kivy.graphics import (Color, Ellipse, Line, Rectangle, Triangle)
        self.canvas.clear()
        x, y = self.pos
        w, h = self.size
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
                import math
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

                # top path: up the left side, round the corner, across to the arrow
                Line(points=[L, B + al, L, T - r]
                            + arc(L + r, T - r, 180, 90)
                            + [R - al, T],
                     width=lw, cap="round", joint="round")
                Triangle(points=[R, T, R - al, T + ah, R - al, T - ah])

                # bottom path: down the right side, round the corner, back to the arrow
                Line(points=[R, T - al, R, B + r]
                            + arc(R - r, B + r, 0, -90)
                            + [L + al, B],
                     width=lw, cap="round", joint="round")
                Triangle(points=[L, B, L + al, B + ah, L + al, B - ah])
            elif k == "sync":
                import math
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
    """A drawn transport glyph that can be tapped (prev / play / next / repeat)."""


class Art(FloatLayout):
    bg = ListProperty([.16, .17, .2, 1])  # neutral tile behind the note glyph
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
            self._image = Image(source=self.source, allow_stretch=True,
                                keep_ratio=True, mipmap=True,
                                fit_mode="cover",
                                size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            self.add_widget(self._image)
        self.art_loaded = self._image is not None


class Fab(ButtonBehavior, FloatLayout):
    pass


class SongRow(RecycleDataViewBehavior, ButtonBehavior, BoxLayout):
    """One row of the song list. The RecycleView reuses rows, so
    ``refresh_view_attrs`` re-points a row at a new track when it is recycled;
    the tap is routed through the app via ``on_release``.
    """
    index = NumericProperty(0)
    title = StringProperty()
    artist = StringProperty()
    duration = StringProperty("0:00")
    path = StringProperty("")
    art = StringProperty("")
    active = BooleanProperty(False)
    fg = ListProperty([1, 1, 1, 1])
    fg_dim = ListProperty([.75, .77, .8, 1])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(active=self._style)
        self._style()

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        # base class copies every key of `data` onto the matching property
        return super().refresh_view_attrs(rv, index, data)

    def on_release(self, instance, *_):
        # ButtonBehavior dispatches the widget instance as an explicit argument
        app = App.get_running_app()
        if app is not None:
            app.play_by_path(self.path)

    def _style(self, *_):
        blue = App.get_running_app().accent
        if self.active:
            self.fg, self.fg_dim = blue, blue
        else:
            self.fg, self.fg_dim = [1, 1, 1, 1], [.75, .77, .8, 1]


class Player(BoxLayout):
    title = StringProperty("Nothing playing")
    artist = StringProperty("")
    art = StringProperty("")
    playing = BooleanProperty(False)
    loop_on = BooleanProperty(False)
    position = NumericProperty(0)  # seconds
    total = NumericProperty(0)

    @staticmethod
    def fmt(sec):
        sec = int(max(0, sec))
        return f"{sec // 60}:{sec % 60:02d}"


class Library(FloatLayout):
    """Root widget; ``inset_*`` hold Android's system-bar insets in physical
    pixels (0 off Android), keeping content clear of the status/nav bars."""

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)
    inset_left = NumericProperty(0)
    inset_right = NumericProperty(0)


class MusicApp(App):
    bg = ListProperty(hex_("#1c1f26"))
    accent = ListProperty(hex_("#7cc4f5"))

    # ------------------------------------------------------------------ #
    # Startup                                                             #
    # ------------------------------------------------------------------ #
    def build(self):
        Window.clearcolor = self.bg
        Builder.load_string(KV)
        self.root_ui = Library()

        self.controller = None
        self.notification = None
        self.tracks = []  # list[dict] from scan_audio_file_paths
        self.current_index = -1
        self.loop_track = False  # repeat current track
        self._pending_seek = None
        self._last_pos = 0.0
        self._scan_in_progress = False
        self._art_generation = 0  # bumped to abandon an outdated art worker

        self.player = self.root_ui.ids.player
        self.seek = self.player.ids.seek

        self._set_status("Starting...")
        # UI refresh + completion detection. There is no on_complete event, so
        # the ticker watches get_pos(); the notification is never polled - app
        # changes call syncPlaybackState() instead.
        self._tick = Clock.schedule_interval(self._on_tick, 0.25)
        Clock.schedule_once(self._start, 2)
        # Pad the UI clear of the status bar / nav buttons (no-op off Android).
        _start_insets_updates(self.root_ui)
        # Clock.schedule_once(lambda _dt: _start_insets_updates(self.root_ui), 0.1)
        return self.root_ui

    @mainthread
    def _start(self, _dt):
        logger.info("starting: request audio permission")
        self.scan_device()

    def on_stop(self):
        self.cleanup()

    # ------------------------------------------------------------------ #
    # Scan / permission                                                   #
    # ------------------------------------------------------------------ #
    def scan_device(self):
        if self._scan_in_progress:
            return
        if not on_android_platform():
            self._set_status("Scanning needs Android (device example)")
            return
        if not is_music_permission_in_manifest():
            self._set_status("Audio permission missing from buildozer.spec "
                             "(android.permissions = READ_MEDIA_AUDIO)")
            return

        if MediaPermissionHandler.has_permission_to_access_audio_files():
            self._scan()
            return

        self._set_status("Requesting audio access...")
        MediaPermissionHandler.ask_permission_to_access_audio_files(
            callback=self._on_permission)

    @mainthread
    def _on_permission(self, granted):
        if not granted:
            self._set_status("Audio access denied")
            return
        self._scan()

    def _scan(self):
        self._scan_in_progress = True
        self.root_ui.ids.fab.disabled = True
        self._set_status("Scanning...")

        def worker():
            try:
                tracks = scan_audio_file_paths()
            except Exception as error:
                logger.exception("scan failed: %s", error)
                tracks = []
            Clock.schedule_once(lambda *_: self._on_scan_done(tracks))

        threading.Thread(target=worker, daemon=True).start()

    @mainthread
    def _on_scan_done(self, tracks):
        self._scan_in_progress = False
        self.root_ui.ids.fab.disabled = False
        self.tracks = tracks
        self.current_index = -1
        start_time = time.time()
        self.set_tracks(tracks)
        logger.info("populate_list took %.3fs", time.time() - start_time)
        if not tracks:
            self._set_status(
                "No loadable file paths - '_data' is hidden on Android 10+ "
                "without All Files Access, or no audio found"
            )
            return
        self._set_status(f"{len(tracks)} songs added")

    def set_tracks(self, tracks):
        """Hand the RecycleView plain dicts; it only builds the visible rows,
        so this stays fast no matter how many tracks there are."""
        songs = self.root_ui.ids.songs
        songs.data = [
            {
                "title": track.get("title") or _basename(track["path"]),
                "artist": track.get("artist") or "Unknown Artist",
                "duration": Player.fmt((track.get("duration") or 0) / 1000.0),
                "path": track["path"],
                "art": _art_cache.get(track["path"], ""),
                "active": False,
            }
            for track in tracks
        ]
        self._start_art_worker(tracks)

    def _start_art_worker(self, tracks):
        """Fill in the list's cover art in the background, top-down."""
        self._art_generation += 1
        generation = self._art_generation

        def worker():
            for track in tracks:
                if generation != self._art_generation:
                    return  # a newer scan/run took over
                art = embedded_art_path(track["path"])
                if art:
                    Clock.schedule_once(
                        lambda _dt, path=track["path"], art=art:
                        self._apply_row_art(path, art, generation))

        threading.Thread(target=worker, daemon=True).start()

    @mainthread
    def _apply_row_art(self, path, art, generation):
        if generation != self._art_generation:
            return
        songs = self.root_ui.ids.songs
        for item in songs.data:
            if item["path"] == path:
                item["art"] = art
                break
        songs.refresh_from_data()  # only changed views are re-applied

    def _art_for(self, path):
        """Instant player art when cached, else fill it in asynchronously."""
        if path in _art_cache:
            return _art_cache[path]

        def worker():
            art = embedded_art_path(path)
            if art:
                Clock.schedule_once(
                    lambda *_: self._set_player_art(path, art))

        threading.Thread(target=worker, daemon=True).start()
        return ""

    @mainthread
    def _set_player_art(self, path, art):
        if (0 <= self.current_index < len(self.tracks)
                and self.tracks[self.current_index]["path"] == path):
            self.player.art = art  # only if the track has not changed since

    # ------------------------------------------------------------------ #
    # Playback                                                            #
    # ------------------------------------------------------------------ #
    def play_by_path(self, path):
        for index, track in enumerate(self.tracks):
            if track["path"] == path:
                self.current_index = index
                self.load_current()
                return

    def load_current(self):
        if not (0 <= self.current_index < len(self.tracks)):
            return
        track = self.tracks[self.current_index]
        title = track.get("title") or _basename(track["path"])

        if self.controller is None:
            self.controller = KivySoundController()
        if not self.controller.load(track["path"]):
            logger.error("Failed to load track: %s", track["path"])
            self._set_status(f"Failed to load: {title}")
            return
        try:
            self.controller.set_on_track_end(self._on_track_end_from_sound)
        except Exception:
            pass
        self.controller.loop = self.loop_track

        logger.info("now playing: %s (%s)", title, track["path"])
        self.controller.play()
        self._update_notification_for_current()
        self._refresh_ui_kivy_for_current()

    def toggle_play_pause(self):
        if self.controller is None:
            # Nothing loaded yet - play the first track if we have any.
            if self.tracks and self.current_index < 0:
                self.current_index = 0
                self.load_current()
            return
        if self.controller.source is None:
            return
        if self.controller.state == "play":
            self.controller.pause()
            logger.info("pause")
        else:
            self.controller.play()
            logger.info("play")
        self.player.playing = self.controller.state == "play"
        self._last_pos = self.controller.get_pos()
        self._sync_notification()

    def next_track(self):
        if not self.tracks:
            return
        if self.current_index + 1 < len(self.tracks):
            self.current_index += 1
            self.load_current()
        # else: end of list; loop-one repeats the player's track itself.

    def previous_track(self):
        if not self.tracks:
            return
        # If we're >3s into the current track, restart it instead.
        if self.controller is not None and self.controller.get_pos() > 3:
            self.perform_seek(0)
            return
        if self.current_index > 0:
            self.current_index -= 1
            self.load_current()

    def toggle_loop(self):
        self.loop_track = not self.loop_track
        if self.controller is not None:
            self.controller.loop = self.loop_track
        self.player.loop_on = self.loop_track
        logger.info("loop -> %s", self.loop_track)

    def perform_seek(self, seconds):
        if self.controller is None or self.controller.source is None:
            return
        target = float(max(0.0, seconds))
        self._pending_seek = target
        self._last_pos = target
        self.controller.seek(target)
        logger.info("seek %.1fs", target)
        self._sync_notification()  # app-driven seek

    def _sync_notification(self):
        if self.notification is not None:
            self.notification.syncPlaybackState()

    def _mark_active(self, path):
        songs = self.root_ui.ids.songs
        changed = False
        for item in songs.data:
            active = (item["path"] == path)
            if item["active"] != active:
                item["active"] = active
                changed = True
        if changed:
            songs.refresh_from_data()  # only changed views are re-applied

    def _set_status(self, text):
        self.root_ui.ids.count.text = text

    # ------------------------------------------------------------------ #
    # Ticker: UI progress + completion detection (no on_complete event)   #
    # ------------------------------------------------------------------ #
    def _on_tick(self, _dt):
        if self.controller is None:
            return
        player = self.player
        length = self.controller.get_length()
        if length > 0:
            player.total = length

        pos = self.controller.get_pos()
        dropped = self._last_pos - pos
        self._last_pos = pos

        if self._pending_seek is not None:
            if abs(pos - self._pending_seek) < 0.75:
                self._pending_seek = None
            else:
                player.position = self._pending_seek
                player.playing = self.controller.state == "play"
                return

        if not self.seek.seeking:
            player.position = min(pos, player.total) if player.total > 0 else pos
        player.playing = self.controller.state == "play"

        if self.controller.state != "play":
            return
        # Guess completion from position: sitting at the end, or a rewind while
        # playing (an endless loop restarting / backend reset). Also catch cases
        # where native completion might not have fired yet.
        at_end = length > 1 and pos >= length - 0.15
        rewound = dropped > 1.0
        if at_end or rewound:
            logger.debug("ticker detected end: at_end=%s rewound=%s pos=%.2f len=%.2f", at_end, rewound, pos, length)
            advanced = self._advance_audio_only()
            if advanced:
                self._update_notification_for_current()
                Clock.schedule_once(lambda dt: self._refresh_ui_kivy_for_current())
                return
            self._track_finished()

    def _on_track_end_from_sound(self, *args):
        logger.info("track end callback from native stop")
        if self.loop_track:
            logger.debug("loop enabled, not advancing")
            return  # Sound will loop naturally via MediaPlayer; don't advance
        # Advancing from native completion
        advanced = self._advance_audio_only()
        if advanced:
            # Update notification immediately (native API, no Clock needed)
            self._update_notification_for_current()
            Clock.schedule_once(lambda dt: self._refresh_ui_kivy_for_current())
            return
        # end of playlist
        if self.controller is not None:
            try:
                self.controller.seek(0)
                self.controller.pause()
            except Exception:
                pass
        self.player.playing = False
        self._reset_seek_ui()
        self._sync_notification()

    def _advance_audio_only(self):
        if not self.tracks:
            return False
        if self.current_index + 1 >= len(self.tracks):
            return False
        self.current_index += 1
        track = self.tracks[self.current_index]
        if self.controller is None:
            self.controller = KivySoundController()
        if self.controller.load(track["path"]):
            try:
                self.controller.set_on_track_end(self._on_track_end_from_sound)
            except Exception:
                pass
            self.controller.loop = self.loop_track
            self.controller.play()
            return True
        return False

    def _update_notification_for_current(self):
        if not (0 <= self.current_index < len(self.tracks)):
            return
        track = self.tracks[self.current_index]
        title = track.get("title") or _basename(track["path"])
        artist = track.get("artist") or "Unknown Artist"
        if self.notification is None:
            self.notification = MediaNotification(
                mediaController=self.controller,
                on_next=self.next_track,
                on_previous=self.previous_track,
            )
        try:
            self.notification.setNowPlaying(str(title), artist)
        except Exception:
            pass
        self._sync_notification()

    def _refresh_ui_kivy_for_current(self):
        if not (0 <= self.current_index < len(self.tracks)):
            return
        track = self.tracks[self.current_index]
        title = track.get("title") or _basename(track["path"])
        artist = track.get("artist") or "Unknown Artist"
        player = self.player
        player.title = title
        player.artist = artist
        player.art = self._art_for(track["path"])
        player.total = (track.get("duration") or 0) / 1000.0
        player.position = 0
        self._pending_seek = None
        self._last_pos = 0.0
        self._mark_active(track["path"])
        self._set_status(f"Track {self.current_index + 1} / {len(self.tracks)}")
        player.playing = self.controller.state == "play" if self.controller else False

    def _track_finished(self):
        """Reached track end. Loop repeats; otherwise advance or stop."""
        if self.loop_track:
            # The sound loops itself; snap the UI back and resync.
            if self.controller is not None:
                self.controller.seek(0)
            self._reset_seek_ui()
            self._sync_notification()
            return

        if self.current_index + 1 < len(self.tracks):
            self.next_track()
            return
        # "Play once": stop at the beginning of the last track.
        if self.controller is not None:
            self.controller.seek(0)
            self.controller.pause()
        self.player.playing = False
        self._reset_seek_ui()
        self._sync_notification()

    def _reset_seek_ui(self):
        self._pending_seek = None
        self._last_pos = 0.0  # don't let the "rewound" check refire after seek(0)
        self.player.position = 0

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #
    def cleanup(self):
        self._art_generation += 1
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None
        if self.controller is not None:
            self.controller.stop_playback()
        if self.notification is not None:
            try:
                self.notification.release()
            except Exception as error:
                logger.exception("error releasing notification: %s", error)
            self.notification = None


if __name__ == "__main__":
    MusicApp().run()