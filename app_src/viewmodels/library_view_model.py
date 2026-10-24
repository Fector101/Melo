"""The view model of the song library.

It owns the list of tracks, the scan flow (including the permission
request) and the cover art of the rows. The view binds to its properties and
listens to ``on_artwork_ready``.
"""

import logging
import threading

from android_notify.config import on_android_platform
from kivy.clock import Clock, mainthread
from kivy.event import EventDispatcher
from kivy.properties import BooleanProperty, ListProperty, StringProperty

logger = logging.getLogger("melo.library")


class LibraryViewModel(EventDispatcher):
    """The state of the library and the commands that change it."""

    #: The tracks of the device, in the order they should be shown.
    tracks = ListProperty([])

    #: The line under the "Your Library" heading.
    status_text = StringProperty("")

    #: Whether a scan is running right now.
    is_scanning = BooleanProperty(False)

    def __init__(self, library_repository, artwork_repository, permissions_repository, **kwargs):
        """
        :param library: the :class:`LibraryRepository` to scan with.
        :param artwork: the :class:`ArtworkRepository` to read the covers from.
        :param permissions: the :class:`PermissionsRepository` to ask with.
        """
        super().__init__(**kwargs)
        self._library = library_repository
        self._artwork = artwork_repository
        self._permissions = permissions_repository
        self._scan_in_progress = False
        self._art_generation = 0  # bumped to abandon an outdated art worker
        self.register_event_type("on_artwork_ready")

    # ------------------------------------------------------------------ #
    # Commands                                                            #
    # ------------------------------------------------------------------ #
    def scan(self):
        """Scan the device for audio files.

        Asks for the audio permission first when it is missing. The scan
        itself runs on a worker thread; ``tracks`` and ``status_text`` are
        updated when it is done.
        """
        if self._scan_in_progress:
            return
        if not on_android_platform():# comment out to scan on desktop
            self.status_text = "Scanning needs Android (device example)"
            return
        if on_android_platform() and not self._permissions.is_declared_in_manifest():
            self.status_text = ("Audio permission missing from buildozer.spec "
                                "(android.permissions = READ_MEDIA_AUDIO)")
            return

        if on_android_platform() and self._permissions.has_audio_access():
            self._start_scan()
            return

        self.status_text = "Requesting audio access..."
        self._permissions.request_audio_access(self._on_permission)

    def set_status(self, text):
        """Set the status line (the player uses it too)."""
        self.status_text = text

    def track_by_path(self, path):
        """The track with ``path``, or ``None``."""
        for track in self.tracks:
            if track.path == path:
                return track
        return None

    def cached_artwork(self, path):
        """The cover art of ``path`` when it is already known (no I/O)."""
        return self._artwork.cached(path)

    # ------------------------------------------------------------------ #
    # Scan                                                                #
    # ------------------------------------------------------------------ #
    @mainthread
    def _on_permission(self, granted):
        if not granted:
            self.status_text = "Audio access denied"
            return
        self._start_scan()

    def _start_scan(self):
        self._scan_in_progress = True
        self.is_scanning = True
        self.status_text = "Scanning..."

        def worker():
            try:
                tracks = self._library.scan()
            except Exception as error:
                logger.exception("scan failed: %s", error)
                tracks = []
            Clock.schedule_once(lambda *_: self._on_scan_done(tracks))

        threading.Thread(target=worker, daemon=True,
                         name="melo-scan").start()

    @mainthread
    def _on_scan_done(self, tracks):
        self._scan_in_progress = False
        self.is_scanning = False
        self.tracks = tracks
        if not tracks:
            self.status_text = ("No loadable file paths - '_data' is hidden on "
                                "Android 10+ without All Files Access, or no "
                                "audio found")
            return
        self.status_text = f"{len(tracks)} songs added"
        self.load_artwork(tracks)

    # ------------------------------------------------------------------ #
    # Cover art                                                           #
    # ------------------------------------------------------------------ #
    def load_artwork(self, tracks=None):
        """Fill in the cover art of ``tracks`` in the background."""
        tracks = self.tracks if tracks is None else tracks
        self._art_generation += 1
        generation = self._art_generation

        def worker():
            for track in tracks:
                if generation != self._art_generation:
                    return  # a newer scan/run took over
                art = self._artwork.extract(track.path)
                if art:
                    Clock.schedule_once(
                        lambda _dt, path=track.path, art=art:
                        self._on_artwork_ready(path, art, generation))

        threading.Thread(target=worker, daemon=True,
                         name="melo-artwork").start()

    @mainthread
    def _on_artwork_ready(self, path, art, generation):
        if generation != self._art_generation:
            return
        self.dispatch("on_artwork_ready", path=path, art=art)

    def on_artwork_ready(self, *_args, **_kwargs):
        """The default handler of the event; the view binds to it."""



# How it works step by step
# Tag each load with a version - When load_artwork() is called, it does self._art_generation += 1 and saves that number into a local variable generation. That generation is "owned" by this specific call and captured by the worker thread.
# New loads invalidate old ones - If load_artwork() is called again before the first worker finishes, _art_generation increases again. The first worker still has its old generation value, while the current value is now higher.
# Old workers bail out cooperatively - The old worker keeps checking if generation != self._art_generation: return. As soon as it notices the numbers don't match (meaning a newer load happened), it stops. It won't process any more tracks, so it saves time extracting art for a library that is no longer being displayed. 
# Results get double-checked - Even if an old worker already extracted some art and scheduled a callback to the UI, that callback also passes its generation. _on_artwork_ready() checks again on the main thread and ignores it if it's stale. This prevents old covers from popping in after the library has already been replaced.