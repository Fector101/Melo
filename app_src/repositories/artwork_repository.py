"""Extracts and caches the cover art that is embedded in audio files."""

import logging
import os
import zlib

from core.android_bridge import get_media_metadata_retriever

logger = logging.getLogger("melo.artwork")


class ArtworkRepository:
    """Cached access to the cover art of a track.

    ``extract`` decodes the embedded picture with the Android
    ``MediaMetadataRetriever``, so it blocks and has to run on a worker
    thread. The bytes are written once into the cache directory, which keeps
    every file to a single decode per install.
    """

    def __init__(self, cache_root=""):
        """
        :param cache_root: a writable directory the art is cached in. When it
            is empty the ``ANDROID_PRIVATE`` environment variable is used
            instead (and, without that, no art is extracted at all).
        """
        self._cache_dir = os.path.join(cache_root, "art_cache") if cache_root \
            else ""
        self._directory_ready = False
        self._paths = {}  # track path -> cached art file ("" when there is none)
        self._failed_extensions = set()  # logged once per file type

    def _directory(self):
        """The cache directory, created on first use ('' when unusable)."""
        if self._directory_ready:
            return self._cache_dir

        self._directory_ready = True
        if not self._cache_dir:
            base = os.environ.get("ANDROID_PRIVATE", "")
            self._cache_dir = os.path.join(base, "art_cache") if base else ""

        if self._cache_dir:
            try:
                os.makedirs(self._cache_dir, exist_ok=True)
            except OSError as error:
                logger.warning("no art cache dir (%s): %s",
                               self._cache_dir, error)
                self._cache_dir = ""
        return self._cache_dir

    def cached(self, track_path):
        """The art path when it is already known, else an empty string.

        Never touches the disk, so it is safe to call from the UI thread.
        """
        return self._paths.get(str(track_path), "")

    def extract(self, track_path):
        """The cached art path of ``track_path`` ('' when it has no art)."""
        key = str(track_path)
        if key in self._paths:
            return self._paths[key]

        result = ""
        retriever_class = get_media_metadata_retriever()
        directory = self._directory() if retriever_class is not None else ""

        if directory:
            stem = os.path.join(directory,
                                f"{zlib.crc32(key.encode('utf-8')):08x}")
            for extension in (".jpg", ".png"):  # reused from an earlier run
                if os.path.exists(stem + extension):
                    result = stem + extension
                    break
            else:
                retriever = None
                try:
                    retriever = retriever_class()
                    retriever.setDataSource(key)
                    art = retriever.getEmbeddedPicture()
                    if art:
                        data = bytes(art)
                        target = stem + (".png"
                                         if data[:8] == b"\x89PNG\r\n\x1a\n"
                                         else ".jpg")
                        with open(target, "wb") as handle:
                            handle.write(data)
                        result = target
                except Exception as error:
                    # pyjnius builds a multi-line message (class, text and
                    # every Java frame), which logcat prints as a wall of
                    # stack. Keep it to one line, and only once per file type.
                    extension = os.path.splitext(key)[1].lower() or "<none>"
                    if extension not in self._failed_extensions:
                        self._failed_extensions.add(extension)
                        reason = (str(error).splitlines()[0] if str(error)
                                  else error)
                        logger.debug("no embedded art for %s files: %s",
                                     extension, reason)
                finally:
                    if retriever is not None:
                        try:
                            retriever.release()
                        except Exception:
                            pass

        self._paths[key] = result
        return result
