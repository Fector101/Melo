"""Runtime permission checks for the audio library."""

import logging

# from android_notify.config import on_android_platform

logger = logging.getLogger("melo.permissions")

from android_notify.internal.permissions import is_music_permission_in_manifest
from android_notify.media.music.helper import MediaPermissionHandler


class PermissionsRepository:
    """Asks Android for the permission to read the audio library."""

    def is_declared_in_manifest(self):
        """Whether ``READ_MEDIA_AUDIO`` is declared in the manifest.

        A missing declaration is a build problem, not a runtime one, so the
        answer is only used to explain it to the user.
        """
        try:
            return bool(is_music_permission_in_manifest())
        except Exception as error:
            logger.warning("manifest check failed: %s", error)
            return True

    def has_audio_access(self):
        """Whether the app may read audio files right now."""
        try:
            return bool(MediaPermissionHandler.has_permission_to_access_audio_files())
        except Exception as error:
            logger.warning("audio access check failed: %s", error)
            return False

    def request_audio_access(self, callback):
        """Ask for the permission; ``callback(granted)`` reports the answer."""
        # if not on_android_platform():
        #     callback(True)
        MediaPermissionHandler.ask_permission_to_access_audio_files(
            callback=callback)
