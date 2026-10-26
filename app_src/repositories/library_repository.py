"""Reads the audio library of the device from MediaStore."""

import logging

from android_notify.config import (get_python_activity_context,
                                   on_android_platform)
from core.android_bridge import autoclass
from models.track import Track

logger = logging.getLogger("melo.library")


class LibraryRepository:
    """Provides the list of tracks that are playable from a file path.

    ``scan`` queries MediaStore, so it blocks and has to run on a worker
    thread. Off Android it returns an empty list.
    """

    def scan(self):
        """Every audio track of the device, sorted by title."""
        if not on_android_platform():
            return []#self.desktop_scan()

        context = get_python_activity_context()
        if not context:
            logger.error("scan: no activity context")
            return []

        resolver = context.getContentResolver()
        uri = autoclass(
            "android.provider.MediaStore$Audio$Media").EXTERNAL_CONTENT_URI
        projection = ["_id", "title", "artist", "duration", "_data"]
        cursor = resolver.query(uri, projection, None, None, None)
        tracks = []

        if cursor:
            title_idx = cursor.getColumnIndex("title")
            artist_idx = cursor.getColumnIndex("artist")
            duration_idx = cursor.getColumnIndex("duration")
            data_idx = cursor.getColumnIndex("_data")
            while cursor.moveToNext():
                try:
                    path = cursor.getString(data_idx)
                except Exception as error:
                    logger.warning("scan: could not get path for track, skipping. Error: %s", error)
                    continue
                tracks.append(Track(
                    path=path,
                    title=cursor.getString(title_idx) or "(unknown title)",
                    artist=cursor.getString(artist_idx) or "",
                    duration_ms=cursor.getLong(duration_idx) or 0,
                ))
            cursor.close()

        tracks.sort(key=lambda track: track.display_title.lower())
        logger.info("scan complete: %d track(s)", len(tracks))
        return tracks

    # def desktop_scan(self):
    #     """Scan for audio files in the user's music directory.

    #     This is a fallback for desktop platforms that don't have MediaStore.
    #     """
    #     import os
    #     from pathlib import Path

    #     music_dir = Path.home() / "Music"
    #     if not music_dir.exists():
    #         logger.warning("desktop_scan: Music directory does not exist")
    #         return []

    #     tracks = []
    #     for root, _, files in os.walk(music_dir):
    #         for file in files:
    #             if file.lower().endswith((".mp3", ".wav", ".flac", ".ogg")):
    #                 path = os.path.join(root, file)
    #                 tracks.append(Track(path=path, title=file, artist="", duration_ms=0))

    #     tracks.sort(key=lambda track: track.display_title.lower())
    #     logger.info("desktop_scan complete: %d track(s)", len(tracks))
    #     return tracks