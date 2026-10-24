"""The audio engine and the media notification behind one small API.

This is the only module that knows about Kivy's ``Sound`` and about
``android_notify``'s ``MediaNotification``. Everything above it works with
tracks and commands.

Why Kivy's own ``SoundLoader``:

- It plays *file paths* only, so tracks are resolved from MediaStore
  ``_data`` instead of ``content://`` URIs. ``_data`` is filtered on Android
  10+ unless the app holds All Files Access, The scan is tested on Android 15 so it's also safe for newer versions.
- There is no ``on_complete`` event, so auto-advance is guessed from the
  position in the app-side ticker (``get_pos()`` at the track length, or a
  rewind while playing).
"""

import logging

from android_notify.config import on_android_platform
from android_notify.media import MediaNotification
from core.android_bridge import run_on_ui_thread

logger = logging.getLogger("melo.playback")

try:
    from kivy.core.audio_output import SoundLoader as KivySoundLoader
except ModuleNotFoundError:  # pragma: no cover - older Kivy
    from kivy.core.audio import SoundLoader as KivySoundLoader



def _load_kivy_sound(path):
    """Load ``path`` through an audio provider that outlives the activity.

    Kivy's provider priority (``PROVIDER_CONFIGS['audio_output']``) is
    ``gstplayer, ffpyplayer, sdl3, avplayer, android``, and
    ``fallback_load()`` takes the first one that supports the extension. With
    the sdl3 bootstrap that means SDL owns playback, and SDL suspends its
    Android audio device as soon as the activity pauses - which happens both
    when the app is left and when the screen turns off. The ``android``
    provider is a framework ``MediaPlayer`` that keeps playing in the
    background, so ask for it explicitly. Kivy falls back to its default
    order on its own if the provider is unavailable or fails to load the
    file, and desktop just uses the default.
    """
    if on_android_platform():
        return KivySoundLoader.load(path, audio_output_provider="android")
    return KivySoundLoader.load(path)


def _keep_cpu_awake(sound):
    """Let the framework player keep decoding while the screen is off.

    ``MediaPlayer`` does not hold a wake lock by itself; without one a deep
    sleep can stall playback. Best-effort only - desktop sounds have no
    player.
    """
    player = getattr(sound, "_mediaplayer", None)
    if player is None:
        return
    try:
        from android_notify.config import get_python_activity_context
        from core.android_bridge import autoclass

        power = autoclass("android.os.PowerManager")
        player.setWakeMode(get_python_activity_context(), power.PARTIAL_WAKE_LOCK)
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
        # i'm using on_stop as completion because kivy fires .stop when sound finsihes playing
        logger.debug("sound stopped: user_stopped=%s, has_cb=%s", self._user_stopped, self._on_track_end is not None)
        if self._user_stopped:
            return
        cb = self._on_track_end
        if cb is None:
            return
        try:
            length = self.get_length()
            pos = self.get_pos()
            logger.debug("end check: length=%.2f pos=%.2f diff=%.3f", length,
                         pos, (length - pos) if length > 0 else -1)
            if length > 1.0 and pos >= length - 0.25:
                logger.info("native completion detected -> advancing")
                if not run_on_ui_thread(cb):
                    try:
                        cb()
                    except Exception as error:
                        logger.debug("end cb failed: %s", error)
        except Exception as error:
            logger.debug("sound stopped end check failed: %s", error)

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

    # I'm using on_stop to seek back to 0 because when using kkivy loop,there's no where to know when the track finished playing.
    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value):
        self._loop = bool(value)
        if self._sound is not None:
            self._sound.loop = False  # app-managed looping so completion fires

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
        """Length may only be known after the sound is loaded (no on_load)."""
        if self._sound is not None and self._sound.length:
            self._length = float(self._sound.length)
        return self._length


class PlaybackRepository:
    """Owns the audio engine and the media notification.

    The rest of the app asks for tracks and commands; it never sees a
    Kivy ``Sound`` or the Android notification.
    """

    def __init__(self):
        self._controller = None
        self._notification = None
        self._loop = False
        self._on_track_end = None
        self._on_next = None
        self._on_previous = None

    # --- wiring -------------------------------------------------------------
    def set_on_track_end(self, callback):
        """The callback the engine calls when a track finished on its own."""
        self._on_track_end = callback

    def set_transport_callbacks(self, on_next=None, on_previous=None):
        """The callbacks the notification's next/previous buttons use."""
        self._on_next = on_next
        self._on_previous = on_previous

    # --- engine -------------------------------------------------------------
    @property
    def has_controller(self):
        """Whether a track is loaded."""
        return self._controller is not None

    @property
    def source(self):
        """The path of the loaded track (None when nothing is loaded)."""
        return self._controller.source if self._controller else None

    @property
    def state(self):
        """``'play'``, ``'pause'`` or ``'stop'``."""
        return self._controller.state if self._controller else "stop"

    @property
    def is_playing(self):
        return self.state == "play"

    @property
    def loop_enabled(self):
        return self._loop

    def set_loop(self, enabled):
        """Repeat the current track."""
        self._loop = bool(enabled)
        if self._controller is not None:
            self._controller.loop = self._loop

    def load(self, path):
        """Load ``path`` and return whether it worked."""
        if self._controller is None:
            self._controller = KivySoundController()
            self._controller.set_on_track_end(self._handle_track_end)
        return self._controller.load(path)

    def play(self):
        if self._controller is not None:
            self._controller.play()

    def pause(self):
        if self._controller is not None:
            self._controller.pause()

    def seek(self, seconds):
        if self._controller is not None:
            self._controller.seek(seconds)

    def get_position(self):
        """The playback position in seconds."""
        return self._controller.get_pos() if self._controller else 0.0

    def get_length(self):
        """The length of the loaded track in seconds (0 when unknown)."""
        return self._controller.get_length() if self._controller else 0.0

    def stop(self):
        if self._controller is not None:
            self._controller.stop_playback()

    # --- notification -------------------------------------------------------
    def set_now_playing(self, title, artist):
        """Show ``title``/``artist`` in the media notification."""
        if self._controller is None:
            return
        if self._notification is None:
            if MediaNotification is None:
                return
            try:
                self._notification = MediaNotification(
                    mediaController=self._controller,
                    on_next=self._on_next,
                    on_previous=self._on_previous,
                )
            except Exception as error:
                logger.warning("no media notification: %s", error)
                return
        try:
            self._notification.setNowPlaying(str(title), artist)
        except Exception as error:
            logger.debug("could not set the now playing info: %s", error)
        self.sync_notification()

    def sync_notification(self):
        """Push the current playback state into the notification."""
        if self._notification is not None:
            self._notification.syncPlaybackState()

    def release(self):
        """Stop the playback and tear the notification down."""
        if self._controller is not None:
            self._controller.stop_playback()
        if self._notification is not None:
            try:
                self._notification.release()
            except Exception as error:
                logger.exception("error releasing notification: %s", error)
            self._notification = None

    # --- internals ----------------------------------------------------------
    def _handle_track_end(self):
        """The engine finished a track: tell the view model about it."""
        callback = self._on_track_end
        if callback is None:
            return
        try:
            callback()
        except Exception as error:
            logger.debug("track end callback failed: %s", error)
