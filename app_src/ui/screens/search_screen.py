"""The search screen: filter the library and play one of the results."""
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import (BooleanProperty, NumericProperty,
                             StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from core.insets import attach_insets
from ui import load_kv, widgets  # noqa: F401  (registers SongRow, Icon, ...)
from ui.format import format_duration


class PlayAllButton(ButtonBehavior, BoxLayout):
    """The pill that plays the first result."""


class SearchScreen(Screen):
    """A live filter over the already-scanned library.

    The screen never scans or owns data: ``SearchViewModel`` supplies the
    tracks and the player view model plays them, so next/previous still follow
    the whole library, not just the filtered rows.
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

        self.bind(
            query=lambda _, value: setattr(self.search_view_model,"user_input",value),
            inset_top=self._on_insets, inset_bottom=self._on_insets
        )
        self.player.bind(current_track=self._on_current_track)
        self.search_view_model.bind(filtered_tracks_value=self.display_found_tracks, search_status_text=self._on_search_status_text)
        # The manager fills filtered_tracks_value before this screen binds, so
        # seed the rows once here instead of waiting for the first keystroke.
        self.display_found_tracks(self.search_view_model,
                                  self.search_view_model.filtered_tracks_value)
        # The manager's inset forwarding is a no-op on this device, so this
        # screen owns its window insets directly (see core.insets).
        attach_insets(self)

    def display_found_tracks(self, instance, tracks):
        """Solely for displaying found tracks after a search"""
        found_tracks = self.search_view_model.filtered_tracks_value

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
        """A result was tapped: play it."""
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
        """Play the first result without changing the playlist."""
        if self.has_results:
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
        Clock.schedule_once(self._focus_search, 0.15)

    def on_leave(self,*args):
        Window.unbind(on_keyboard=self._on_window_key)

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
