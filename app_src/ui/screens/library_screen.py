"""The library screen: the list of tracks, the player and the scan button."""

from kivy.properties import NumericProperty, StringProperty
from kivy.uix.floatlayout import FloatLayout

from ui import widgets  # noqa: F401  (importing registers the widgets)
from ui.format import format_duration


class LibraryScreen(FloatLayout):
    """The root widget of the app.

    It binds to the view models and forwards the user's actions to them; it
    never touches a repository itself.
    """

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)
    inset_left = NumericProperty(0)
    inset_right = NumericProperty(0)

    #: The line under the heading.
    status_text = StringProperty("")

    def __init__(self, library, player, **kwargs):
        """
        :param library: the :class:`LibraryViewModel` with the track list.
        :param player: the :class:`PlayerViewModel` with the playback state.
        """
        super().__init__(**kwargs)
        self.library = library
        self.player = player
        self._rows = []
        self._bind_view_models()
        self._bind_widgets()

    # ------------------------------------------------------------------ #
    # Wiring                                                              #
    # ------------------------------------------------------------------ #
    def _bind_view_models(self):
        library = self.library
        library.bind(status_text=self._on_status_text,
                     tracks=self._on_tracks,
                     is_scanning=self._on_is_scanning)
        library.bind(on_artwork_ready=self._on_artwork_ready)

        player = self.player
        player.bind(title=self._on_player_state,
                    artist=self._on_player_state,
                    art=self._on_player_state,
                    is_playing=self._on_player_state,
                    duration=self._on_player_state,
                    loop_enabled=self._on_player_state,
                    current_track=self._on_current_track,
                    position=self._on_position)

    def _bind_widgets(self):
        player_bar = self.ids.player_bar
        player_bar.ids.prev_button.bind(on_release=self._on_previous)
        player_bar.ids.play_button.bind(on_release=self._on_toggle_play_pause)
        player_bar.ids.next_button.bind(on_release=self._on_next)
        player_bar.ids.repeat_button.bind(on_release=self._on_toggle_loop)
        player_bar.ids.seek.on_seek_requested = self._on_seek
        player_bar.ids.seek.bind(seeking=self._on_seeking)
        self.ids.fab.bind(on_release=self._on_scan)

    # ------------------------------------------------------------------ #
    # The list                                                            #
    # ------------------------------------------------------------------ #
    def _on_tracks(self, _instance, tracks):
        """Rebuild the rows of the list."""
        current = self.player.current_track
        active_path = current.path if current is not None else ""
        self._rows = [
            {
                "title": track.display_title,
                "artist": track.display_artist,
                "duration": format_duration(track.duration_seconds),
                "path": track.path,
                "art": self.library.cached_artwork(track.path),
                "active": track.path == active_path,
                "on_select": self._on_row_selected,
            }
            for track in tracks
        ]
        self.ids.songs.data = self._rows

    def _on_artwork_ready(self, _instance, path, art):
        """The cover of a track was extracted: show it in its row."""
        for row in self._rows:
            if row["path"] == path:
                row["art"] = art
                break
        self.ids.songs.refresh_from_data()

    def _on_row_selected(self, path):
        """A row was tapped: play that track."""
        track = self.library.track_by_path(path)
        if track is not None:
            self.player.play_track(track)

    def _on_current_track(self, _instance, track):
        """Highlight the row of the track that is playing."""
        active = track.path if track is not None else ""
        changed = False
        for row in self._rows:
            is_active = row["path"] == active
            if row["active"] != is_active:
                row["active"] = is_active
                changed = True
        if changed:
            self.ids.songs.refresh_from_data()

    # ------------------------------------------------------------------ #
    # The player                                                          #
    # ------------------------------------------------------------------ #
    def _on_player_state(self, _instance, _value):
        """Show what the player view model reports."""
        player_bar = self.ids.player_bar
        player_bar.title = self.player.title
        player_bar.artist = self.player.artist
        player_bar.art = self.player.art
        player_bar.playing = self.player.is_playing
        player_bar.loop_on = self.player.loop_enabled
        player_bar.total = self.player.duration

    def _on_position(self, _instance, value):
        """Move the seek bar."""
        self.ids.player_bar.position = value

    def _on_seek(self, seconds):
        """The user let go of the seek bar."""
        self.player.seek(seconds)

    def _on_seeking(self, _instance, value):
        """The user is dragging the seek bar."""
        self.player.set_seeking(value)

    # ------------------------------------------------------------------ #
    # The buttons                                                         #
    # ------------------------------------------------------------------ #
    def _on_previous(self, *_):
        self.player.previous_track()

    def _on_toggle_play_pause(self, *_):
        self.player.toggle_play_pause()

    def _on_next(self, *_):
        self.player.next_track()

    def _on_toggle_loop(self, *_):
        self.player.toggle_loop()

    def _on_scan(self, *_):
        """The scan button was tapped."""
        self.library.scan()

    def _on_status_text(self, _instance, value):
        self.status_text = value

    def _on_is_scanning(self, _instance, value):
        self.ids.fab.disabled = value
