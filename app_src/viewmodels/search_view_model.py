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
    search_status_text = StringProperty("scan ongoing...")

    def __init__(self, library_repository, artwork_repository, player_repo,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.polling_clock_for_scan_tracks = None
        self.past_search_query_clock = None
        self._library_repository = library_repository
        self._artwork_repository = artwork_repository
        self.player_repo = player_repo

        self.get_cached_tracks()
        self.bind(user_input=self.run_search_buffer)

    def get_cached_tracks(self,dt=None):
        # libray screen does the scan to populate LibraryRepository.cached_tracks value,
        # instead of cancelling and doing more scan work here i'll just wait for it
        if self.polling_clock_for_scan_tracks:
            self.polling_clock_for_scan_tracks.cancel()
        if not self._library_repository.scan_in_progress:
            self._init_tracks_after_initialization(self._library_repository.cached_tracks)
        else:
            self.polling_clock_for_scan_tracks = Clock.schedule_interval(self.get_cached_tracks,1)

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
        self.__set_search_status_text_state()

    def filter_tracks(self, user_input):
        """Filtering based on input against title and artist."""
        # `casefold` over lower so chars with alternative lowercases match properly
        user_input = (user_input or "").strip().casefold()
        if not user_input:
            self.filtered_tracks_value = self.tracks
            self.__set_search_status_text_state()
            return

        filtered = []
        for track in self.tracks:
            if (user_input in track.display_title.casefold() or user_input in track.display_artist.casefold()):
                filtered.append(track)
        self.filtered_tracks_value = filtered
        self.__set_search_status_text_state()

    def cached_artwork(self, path):
        """The cover art of ``path`` when it is already known (no I/O)."""
        return self._artwork_repository.cached(path)

    def track_by_path(self, path):
        """The track with ``path``, or ``None``."""
        for track in self.tracks:
            if track.path == path:
                return track
        return None

    def set_playlist_from_results(self):
        """Make the current results the playlist the player walks through."""
        self.player_repo.current_playlist = self.filtered_tracks_value

    @mainthread
    def set_search_status_text(self, value):
        self.search_status_text = value

    def __set_search_status_text_state(self):
        if self.filtered_tracks_value:
            self.set_search_status_text("")
        elif self._library_repository.scan_in_progress:
            self.set_search_status_text("scan ongoing...")
        else:
            self.set_search_status_text("No songs match your search")
