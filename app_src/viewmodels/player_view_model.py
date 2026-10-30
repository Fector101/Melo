"""The view model of the player.

It holds what is playing and the transport commands, and it owns the ticker
that keeps the progress bar in sync. The end of a track is reported by the
engine's ``on_stop`` callback (see ``KivySoundController``), not the ticker.
"""

import logging
import threading

from kivy.clock import Clock, mainthread

from kivy.event import EventDispatcher
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty

logger = logging.getLogger("melo.player")

TICK_INTERVAL = 0.25  # seconds between two progress updates
RESTART_AFTER = 3.0  # "previous" restarts the track after this many seconds


class PlayerViewModel(EventDispatcher):
    """The state of the player and the commands that change it."""

    #: The track that is loaded (None when nothing is loaded).
    current_track = ObjectProperty(None, allownone=True)

    #: The title / artist / cover of the loaded track.
    title = StringProperty("Nothing playing")
    artist = StringProperty("")
    art = StringProperty("")

    #: Whether the audio is playing right now.
    is_playing = BooleanProperty(False)

    #: The playback position and the length of the track, in seconds.
    position = NumericProperty(0.0)
    duration = NumericProperty(0.0)

    #: Whether the current track repeats.
    loop_enabled = BooleanProperty(False)

    #: Whether the user is dragging the seek bar (the ticker keeps quiet).
    is_seeking = BooleanProperty(False)

    def __init__(self, playback_repository, library_viewmodel, artwork_repository, **kwargs):
        """
        :param playback: the :class:`PlaybackRepository` to play through.
        :param library: the :class:`LibraryViewModel` with the playlist.
        :param artwork: the :class:`ArtworkRepository` for the cover.
        """
        super().__init__(**kwargs)
        self._playback_repository = playback_repository
        self._library_viewmodel = library_viewmodel
        self._artwork_repository = artwork_repository
        self._index = -1
        self._tick = None
        self._pending_seek = None
        self._last_pos = 0.0
        
        self.bind(current_track=self._on_current_track)

        self._library_viewmodel.bind(tracks=self._on_tracks_changed)
        
        self._playback_repository.set_on_track_end(self._on_track_end)
        self._playback_repository.set_transport_callbacks(on_next=self.next_track, on_previous=self.previous_track)
        self._playback_repository.set_on_playing_state_change(self._set_playing_state)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #
    def start_ticking(self):
        """Start the progress ticker."""
        if self._tick is None:
            self._tick = Clock.schedule_interval(self._on_tick, TICK_INTERVAL)

    def stop_ticking(self):
        """Stop the progress ticker."""
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None

    # ------------------------------------------------------------------ #
    # Commands                                                            #
    # ------------------------------------------------------------------ #
    def play_track(self, track):
        """Play ``track`` - a row of the list was tapped."""
        index = self._index_of(track)
        if index is None:
            return
        self._index = index
        self._load_current()

    def toggle_play_pause(self):
        """Start or pause the playback."""
        if not self._playback_repository.has_controller:
            # Nothing loaded yet - play the first track if we have any.
            tracks = self._library_viewmodel.tracks
            if tracks and self._index < 0:
                self._index = 0
                self._load_current()
            return
        if self._playback_repository.source is None:
            return
        if self._playback_repository.is_playing:
            self._playback_repository.pause()
            self.stop_ticking()
            logger.info("pause")
        else:
            self._playback_repository.play()
            self.start_ticking()
            logger.info("play")
        self._last_pos = self._playback_repository.get_position()
        self._playback_repository.sync_notification()

    def next_track(self):
        """Play the next track of the list."""
        tracks = self._library_viewmodel.tracks
        if not tracks:
            return
        if self._index + 1 < len(tracks):
            self._index += 1
            return self._load_current()
        return False # did'nt advance
        # else: end of list; loop-one repeats the player's track itself.

    def previous_track(self):
        """Play the previous track - or restart the current one."""
        tracks = self._library_viewmodel.tracks
        if not tracks:
            return
        if _should_prev_button_only_restart_playing_song(self._playback_repository):
            self._restart_playing_song(resume=self._playback_repository.is_playing)
            return
        if self._index > 0:
            self._index -= 1
            self._load_current()

    def toggle_loop(self):
        """Repeat the current track."""
        self.loop_enabled = not self.loop_enabled
        self._playback_repository.set_loop(self.loop_enabled)
        logger.info("loop -> %s", self.loop_enabled)

    def seek(self, seconds):
        """Jump to ``seconds`` of the loaded track."""
        if not self._playback_repository.has_controller or self._playback_repository.source is None:
            return
        target = float(max(0.0, seconds))
        self._pending_seek = target
        self._last_pos = target
        self._safe_set_position(target)# self.position = target
        self._playback_repository.seek(target)
        logger.info("seek %.1fs", target)
        self._playback_repository.sync_notification()

    def set_seeking(self, seeking):
        """Called while the user drags the seek bar."""
        self.is_seeking = bool(seeking)


    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #
    @mainthread
    def _set_playing_state(self, state):
        self.is_playing = state

    def _current(self):
        """The track that should be playing (None when there is none)."""
        tracks = self._library_viewmodel.tracks
        if 0 <= self._index < len(tracks):
            return tracks[self._index]
        return None

    def _index_of(self, track):
        for index, candidate in enumerate(self._library_viewmodel.tracks):
            if candidate.path == track.path:
                return index
        return None

    def _load_current(self):
        """Load the current track into the engine and start it."""
        track = self._current()
        if track is None:
            return False
        if not self._playback_repository.load(track.path):
            logger.error("failed to load track: %s", track.path)
            self._library_viewmodel.set_status(f"Failed to load: {track.display_title}")
            return False
        self._playback_repository.set_loop(self.loop_enabled)
        logger.info("now playing: %s (%s)", track.display_title, track.path)
        self.start_ticking()
        self._playback_repository.play()
        self._publish_now_playing()
        self._refresh_for_current()
        return True

    def _publish_now_playing(self):
        """Show the current track in the media notification."""
        track = self._current()
        if track is None:
            return
        self._playback_repository.set_now_playing(track.display_title, track.display_artist)

    @mainthread
    def _refresh_for_current(self):
        """Push the state of the current track into the view model."""
        track = self._current()
        if track is None:
            return
        self.current_track = track  # -> the title, artist and cover
        self.duration = track.duration_seconds
        self.position = 0.0
        self._pending_seek = None
        self._last_pos = 0.0
        self._library_viewmodel.set_status(f"Track {self._index + 1} / {len(self._library_viewmodel.tracks)}")

    def _on_current_track(self, _instance, track):
        """The loaded track changed: show its title, artist and cover."""
        if track is None:
            self.title = "Nothing playing"
            self.artist = ""
            self.art = ""
            return
        self.title = track.display_title
        self.artist = track.display_artist
        self.art = self._art_for(track.path)

    def _on_tracks_changed(self, _instance, _tracks):
        """A new scan replaced the library: the playlist starts over."""
        self._index = -1

    def _art_for(self, path):
        """The cover of ``path`` when it is cached, else it is loaded async."""
        art = self._artwork_repository.cached(path)
        if art:
            return art

        def worker():
            found = self._artwork_repository.extract(path)
            if found:
                Clock.schedule_once(lambda *_: self._set_player_art(path, found))

        threading.Thread(target=worker, daemon=True, name="melo-player-art").start()
        return ""

    def _set_player_art(self, path, art):
        """Show ``art`` when the player still plays that track."""
        track = self._current()
        if track is not None and track.path == path:
            self.art = art

    @mainthread
    def _safe_set_position(self, target_position):
        # Safe fallback once Kivy's loop wakes back up
        self.position = target_position

    def _on_tick(self, _dt):
        if not self._playback_repository.has_controller:
            return

        length = self._playback_repository.get_length()
        if length > 0:
            self.duration = length

        pos = self._playback_repository.get_position()
        self._last_pos = pos

        if self._pending_seek is not None:
            if abs(pos - self._pending_seek) < 0.75:
                self._pending_seek = None
            else:
                self.position = self._pending_seek
                return

        if not self.is_seeking:
            self.position = min(pos, self.duration) if self.duration > 0 else pos

    def _on_track_end(self, *args):
        """The engine stopped on its own: the track is over."""
        logger.info("track end callback from native stop")
        self.start_ticking()
        
        if self.loop_enabled:
            self._restart_playing_song()
            return
        
        advanced = self.next_track()
        if advanced:
            return
        
        # end of the playlist
        self._playback_repository.seek(0)
        self._playback_repository.pause()
        self._reset_seek_ui()
        self._playback_repository.sync_notification()

    @mainthread
    def _reset_seek_ui(self):
        self._pending_seek = None
        self._last_pos = 0.0  # don't let the "rewound" check refire
        self.position = 0.0

    def _restart_playing_song(self, resume=True):
        """Restart the loaded track from 0, optionally resuming playback."""
        logger.debug("restarting track from 0 (resume=%s)", resume)
        self._playback_repository.seek(0)
        if resume: # keeps the song paused state when user clicks prev btn
            self._playback_repository.play()
        self._reset_seek_ui()
        self._playback_repository.sync_notification()

    def end_operations(self):
        """End player operations"""
        self.stop_ticking()
        self._playback_repository.release()

def _should_prev_button_only_restart_playing_song(_playback_repository):
    """Helper to check if when previous btn is clicked, should player go to previous song or restart current song"""
    # If we're >3s into the current track, restart it instead.
    return _playback_repository.has_controller and _playback_repository.get_position() > RESTART_AFTER
