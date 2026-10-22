"""The domain model: what a track is.

Plain data, no Kivy and no Android, so every layer above can rely on it.
"""

import os
from dataclasses import dataclass


def basename(path):
    """Best-effort human name for a file path."""
    name = str(path or "").rstrip("/")
    return os.path.basename(name) or name


@dataclass(frozen=True)
class Track:
    """One playable track of the device library."""

    path: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    album: str = ""

    @property
    def duration_seconds(self):
        """The track length in seconds."""
        return max(0.0, float(self.duration_ms or 0) / 1000.0)

    @property
    def display_title(self):
        """The title to show, with a fallback for untitled tracks."""
        return self.title or basename(self.path)

    @property
    def display_artist(self):
        """The artist to show, with a fallback for unknown ones."""
        return self.artist or "Unknown Artist"
