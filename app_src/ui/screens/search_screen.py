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

    The screen never scans or owns data: it reads ``library.tracks`` and uses
    the existing player view model, so next/previous still follow the whole
    library, not just the filtered rows.
    """

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)

    #: What the user typed; changing it re-runs the filter.
    query = StringProperty("")

    #: The line above the results ("12 songs").
    result_count = StringProperty("0 songs")

    has_results = BooleanProperty(False)

    def __init__(self, library, player, **kwargs):
        """
        :param library: the :class:`LibraryViewModel` with the track list.
        :param player: the :class:`PlayerViewModel` used to play a result.
        """
        super().__init__(**kwargs)
        self.library = library
        self.player = player
        self._rows = []
        self._matches = []

        self.bind(query=self._on_query,
                  inset_top=self._on_insets,
                  inset_bottom=self._on_insets)
        self.library.bind(tracks=self._on_tracks,
                          on_artwork_ready=self._on_artwork_ready)
        self.player.bind(current_track=self._on_current_track)

        # The manager's inset forwarding is a no-op on this device, so this
        # screen owns its window insets directly (see core.insets).
        attach_insets(self)
        self._apply_filter()

    # ------------------------------------------------------------------ #
    # Filtering                                                           #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _matches_query(track, query):
        """Case-insensitive match on the fields a user would search for."""
        needle = (query or "").strip().casefold()
        if not needle:
            return True
        fields = (getattr(track, "display_title", ""),
                  getattr(track, "display_artist", ""),
                  getattr(track, "album", ""))
        return any(needle in str(field or "").casefold() for field in fields)

    def _on_query(self, _instance, query):
        self._apply_filter()

    def _on_tracks(self, *_):
        self._apply_filter()

    def _row_for(self, track, active_path):
        return {
            "title": track.display_title,
            "artist": track.display_artist,
            "duration": format_duration(track.duration_seconds),
            "path": track.path,
            "art": self.library.cached_artwork(track.path),
            "active": track.path == active_path,
            "on_select": self._on_row_selected,
        }

    def _apply_filter(self):
        """Rebuild the result rows from the current query."""
        matches = [track for track in self.library.tracks
                   if self._matches_query(track, self.query)]
        self._matches = matches

        current = self.player.current_track
        active_path = current.path if current is not None else ""
        self._rows = [self._row_for(track, active_path) for track in matches]
        self.ids.results.data = self._rows

        count = len(matches)
        self.result_count = f"{count} song{'' if count == 1 else 's'}"
        self.has_results = bool(matches)

    def _on_artwork_ready(self, _instance, path, art):
        """A cover was extracted: update the matching result row."""
        target = None
        for row in self._rows:
            if row["path"] == path:
                row["art"] = art
                target = row
                break
        if target is None:
            return

        rv = self.ids.results
        try:
            adapter = getattr(rv, "view_adapter", None)
            if adapter is not None and hasattr(adapter, "get_visible_view"):
                for view in adapter.get_visible_view() or []:
                    if getattr(view, "path", None) == path:
                        view.art = art
                        return
        except Exception:
            pass
        rv.refresh_from_data()

    def _on_current_track(self, _instance, track):
        """Highlight the result that is playing."""
        active = track.path if track is not None else ""
        changed = False
        for row in self._rows:
            is_active = row["path"] == active
            if row["active"] != is_active:
                row["active"] = is_active
                changed = True
        if changed:
            self.ids.results.refresh_from_data()

    def _on_row_selected(self, path):
        """A result was tapped: play it."""
        track = self.library.track_by_path(path)
        if track is not None:
            self.player.play_track(track)

    # ------------------------------------------------------------------ #
    # Commands from the KV                                                #
    # ------------------------------------------------------------------ #
    def clear_query(self):
        """The X button was tapped."""
        self.ids.search_input.text = ""
        self.query = ""

    def play_all(self, *_):
        """Play the first result without changing the playlist."""
        if self._matches:
            self.player.play_track(self._matches[0])

    def go_back(self, *_):
        """Return to the library screen."""
        if self.manager is not None:
            self.manager.current = "library"

    # ------------------------------------------------------------------ #
    # Android back / desktop Escape                                       #
    # ------------------------------------------------------------------ #
    def on_enter(self):
        Window.bind(on_keyboard=self._on_window_key)
        Clock.schedule_once(self._focus_search, 0.15)

    def on_leave(self):
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
        self.inset_bottom = inset_bottom
        container = self.ids.main_container
        container.padding = [container.padding[0], inset_top,
                             container.padding[2], inset_bottom]

    def _on_insets(self, *_):
        self.apply_padding(self.inset_top, self.inset_bottom)


load_kv("search_screen.kv")
