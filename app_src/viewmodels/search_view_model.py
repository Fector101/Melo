"""Search state and filtering for the search screen."""
from kivy.clock import Clock, mainthread
from kivy.event import EventDispatcher
from kivy.properties import ListProperty, StringProperty, NumericProperty


class SearchViewModel(EventDispatcher):
    # this is a list of all the songs currently displayed on search screen
    tracks = ListProperty()

    # filtered tracks after search, this what is going to by displayed on screen
    filtered_tracks_value = ListProperty()

    # the current value user has passed in for search
    user_input = StringProperty()

    # this is the delay to perform search after user is done typing to avoid lags
    delay_before_search = NumericProperty(0.2)

    def __init__(self, library_repository, artwork_repository, player_repo,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.past_search_query_clock = None
        self._library_repository = library_repository
        self._artwork_repository = artwork_repository
        self.player_repo = player_repo

        self._init_tracks_after_initialization(
            self._library_repository.cached_tracks)
        self.bind(user_input=self.run_search_buffer)

    def run_search_buffer(self, _, value):
        """Debounce a search so a fast typist only pays for the final query."""
        if self.past_search_query_clock:
            self.past_search_query_clock.cancel()
        self.past_search_query_clock = Clock.schedule_once(
            lambda _: self.filter_tracks(value), self.delay_before_search)

    @mainthread
    def _init_tracks_after_initialization(self, tracks):
        self.tracks = tracks
        self.filtered_tracks_value = tracks

    def filter_tracks(self, user_input):
        """Filtering based on input against title, album and artist."""
        # `casefold` over lower so chars with alternative lowercases match properly
        needle = (user_input or "").strip().casefold()
        if not needle:
            self.filtered_tracks_value = self.tracks
            return

        filtered = []
        for track in self.tracks:
            if (needle in track.title.casefold()
                    or needle in track.artist.casefold()
                    or needle in track.album.casefold()):
                filtered.append(track)
        self.filtered_tracks_value = filtered

    def cached_artwork(self, path):
        """The cover art of ``path`` when it is already known (no I/O)."""
        return self._artwork_repository.cached(path)

    def track_by_path(self, path):
        """The track with ``path``, or ``None``."""
        self.player_repo.current_playlist = self.filtered_tracks_value
        for track in self.tracks:
            if track.path == path:
                return track
        return None
