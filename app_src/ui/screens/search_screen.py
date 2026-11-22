"""The search screen: filter the library and play one of the results."""
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import (BooleanProperty, NumericProperty,
                             StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from ui import load_kv, widgets  # noqa: F401  (registers SongRow, Icon, ...)
from ui.format import format_duration


class PlayAllButton(ButtonBehavior, BoxLayout):
    """The pill that plays the first result."""


class SearchScreen(Screen):
    """A live filter over the already-scanned library.

    The screen never scans or owns data: ``SearchViewModel`` supplies the
    tracks and the player view model plays them. Playing a result makes the
    current results the playlist, so next/previous walk the visible matches.
    """

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)

    #: What the user typed; changing it re-runs the filter.
    query = StringProperty("")

    #: The line above the results ("12 songs").
    result_count = StringProperty("0 songs")

    has_results = BooleanProperty(False)

    search_status_text = StringProperty("scan ongoing...") # "No songs match your search" or "scan ongoing..."

    def __init__(self, search_view_model, player_view_model, **kwargs):
        """
        :param search_view_model: the :class:`SearchViewModel` with the tracks.
        :param player_view_model: the :class:`PlayerViewModel` used to play a result.
        """
        super().__init__(**kwargs)
        self.search_view_model = search_view_model
        self.player = player_view_model

        self._displayed_tracks_recycle_view_data = []
        self._focus_event = None

        self.bind(
            query=lambda _, value: setattr(self.search_view_model,"user_input",value),
            inset_top=self._on_insets, inset_bottom=self._on_insets
        )
        self.player.bind(current_track=self._on_current_track)
        self.search_view_model.bind(filtered_tracks_value=self.display_found_tracks, search_status_text=self._on_search_status_text)
        self.display_found_tracks(self.search_view_model, self.search_view_model.filtered_tracks_value)
        

    def display_found_tracks(self, instance, tracks):
        """Solely for displaying found tracks after a search"""
        found_tracks = tracks

        current = self.player.current_track
        active_path = current.path if current else ""

        self._displayed_tracks_recycle_view_data = [self._row_for(track, active_path) for track in found_tracks]
        self.ids.results.data = self._displayed_tracks_recycle_view_data

        count = len(found_tracks)
        self.result_count = f"{count} song{'' if count == 1 else 's'}"
        self.has_results = bool(count)

    def _row_for(self, track, active_path):
        return {
            "title": track.display_title,
            "artist": track.display_artist,
            "duration": format_duration(track.duration_seconds),
            "path": track.path,
            "art": self.search_view_model.cached_artwork(track.path),
            "active": track.path == active_path,
            "on_select": self._on_row_selected,
        }

    def _on_current_track(self, _instance, track):
        """Highlight the result that is playing."""
        active = track.path if track is not None else ""
        changed = False
        for row in self._displayed_tracks_recycle_view_data:
            is_active = row["path"] == active
            if row["active"] != is_active:
                row["active"] = is_active
                changed = True
        if changed:
            self.ids.results.refresh_from_data()

    def _on_row_selected(self, path):
        """A result was tapped: play it with the current results as playlist."""
        self.search_view_model.set_playlist_from_results()
        track = self.search_view_model.track_by_path(path)
        if track is not None:
            self.player.play_track(track) # don't pass another vm into a vm

    # ------------------------------------------------------------------ #
    # Commands from the KV                                                #
    # ------------------------------------------------------------------ #
    def clear_query(self):
        """The X button was tapped."""
        self.ids.search_input.text = ""
        self.query = ""

    def play_all(self, *_):
        """Play the first result with the current results as the playlist."""
        if self.has_results:
            self.search_view_model.set_playlist_from_results()
            path = self.search_view_model.filtered_tracks_value[0].path
            track = self.search_view_model.track_by_path(path)
            self.player.play_track(track)

    def go_back(self, *_):
        """Return to the library screen."""
        if self.manager is not None:
            self.manager.current = "library"

    # ------------------------------------------------------------------ #
    # Android back / desktop Escape                                       #
    # ------------------------------------------------------------------ #
    def on_enter(self,*args):
        Window.bind(on_keyboard=self._on_window_key)
        self._focus_event = Clock.schedule_once(self._focus_search, 0.15)

    def on_leave(self,*args):
        Window.unbind(on_keyboard=self._on_window_key)
        if self._focus_event is not None:
            self._focus_event.cancel()
            self._focus_event = None

    def _focus_search(self, _dt):
        self.ids.search_input.focus = True

    def _on_window_key(self, _window, key, *_):
        if (key == 27 and self.manager is not None
                and self.manager.current == "search"):
            self.go_back()
            return True
        return False

    # ------------------------------------------------------------------ #
    # Insets                                                              #
    # ------------------------------------------------------------------ #
    def apply_padding(self, inset_top, inset_bottom):
        """Keep the layout clear of the system bars (Android 15+).

        The horizontal padding comes from the KV and must survive; the manager
        may also call this with its own (stale) inset values when the screen is
        added, before this screen's own listener reports the real ones.
        """
        self.inset_top = inset_top
        padded = inset_top + 10
        self.inset_bottom = inset_bottom
        container = self.ids.main_container
        container.padding = [container.padding[0], padded, container.padding[2], inset_bottom]

    def _on_insets(self, *_):
        self.apply_padding(self.inset_top, self.inset_bottom)

    def _on_search_status_text(self, _, value):
        self.search_status_text = value

load_kv("search_screen.kv")
