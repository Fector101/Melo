"""The library screen: the list of tracks, the player and the scan button."""

from kivy.properties import NumericProperty, StringProperty
from kivy.uix.screenmanager import Screen

from ui import load_kv, widgets  # noqa: F401  (importing registers the widgets)
from ui.format import format_duration


class LibraryScreen(Screen):
    """The root widget of the app.

    It binds to the view models and forwards the user's actions to them; it
    never touches a repository itself.
    """

    inset_top = NumericProperty(0)
    inset_bottom = NumericProperty(0)

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
        self._update_chip = None
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

        # The app-wide PlayerHost owns the player-widget bindings. This screen
        # only needs current_track to highlight the row that is playing.
        self.player.bind(current_track=self._on_current_track)

    def _bind_widgets(self):
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
        target = None
        for row in self._rows:
            if row["path"] == path:
                row["art"] = art
                target = row
                break
        if target is None:
            return
        rv = self.ids.songs
        try:
            adapter = getattr(rv, "view_adapter", None)
            if adapter is not None and hasattr(adapter, "get_visible_view"):
                for view in adapter.get_visible_view():
                    if getattr(view, "path", None) == path:
                        view.art = art
                        return
        except Exception:
            pass
        rv.refresh_from_data()

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
    # The scan button (player controls live in the app-wide PlayerHost)   #
    # ------------------------------------------------------------------ #
    def _on_scan(self, *_):
        """The scan button was tapped."""
        self.library.scan()

    def _on_status_text(self, _instance, value):
        self.status_text = value

    def _on_is_scanning(self, _instance, value):
        self.ids.fab.disabled = value

    # ------------------------------------------------------------------ #
    # The update chip                                                     #
    # ------------------------------------------------------------------ #
    def show_update_chip(self, version):
        """Show (or re-show) the "update available" chip on this screen."""
        if self._update_chip is None:
            from ui.widgets.update import UpdateChip

            self._update_chip = UpdateChip(
                text=("Update available  \u00b7  " + str(version)).strip(),
                on_release=self._on_update_chip,
                pos_hint={"right": 0.98},
            )
            self.bind(size=self._place_update_chip,
                      inset_top=self._place_update_chip)
        self._update_chip.show(self)

    def _place_update_chip(self, *_):
        if self._update_chip is not None and self._update_chip.parent is not None:
            self._update_chip.place(self)

    def _on_update_chip(self, *_):
        self.manager.current = "update"

    # ------------------------------------------------------------------ #
    # Insets                                                              #
    # ------------------------------------------------------------------ #
    def apply_padding(self, inset_top, inset_bottom):
        """Keep the layout clear of the system bars (Android 15+ edge-to-edge)."""
        self.inset_top = inset_top
        self.inset_bottom = inset_bottom
        self.ids.main_container.padding = [0, inset_top, 0, inset_bottom]


load_kv("library_screen.kv")
