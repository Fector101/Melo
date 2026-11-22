"""Runtime permission checks for the audio library."""

import logging

logger = logging.getLogger("melo.permissions")

# This won't be needed after version 1.62.0, 
# I'll implement an interal way not to initilize on startup

# Mirrors android_notify's request guard. Call the lower-level functions from
# android_notify.internal.permissions directly: the MediaPermissionHandler
# wrapper lives in android_notify.media.music.helper, which loads MediaPlayer
# and the whole media package (a dozen Java classes) on first permission check.
_requesting_audio_access = False


def _set_requesting_audio_access(state=True, **_):
    global _requesting_audio_access
    _requesting_audio_access = bool(state)


class MeloPermissions:
    """Asks Android for the permission to read the audio library."""

    
    @staticmethod
    def is_declared_in_manifest():
        """Whether ``READ_MEDIA_AUDIO`` is declared in the manifest.

        A missing declaration is a build problem, not a runtime one, so the
        answer is only used to explain it to the user.
        """
        try:
            from android_notify.internal.permissions import is_music_permission_in_manifest

            return bool(is_music_permission_in_manifest())
        except Exception as error:
            logger.warning("manifest check failed: %s", error)
            return True

    @staticmethod
    def has_audio_access():
        """Whether the app may read audio files right now."""
        # from android_notify.media.music.helper import MediaPermissionHandler
        from android_notify.internal.permissions import has_permission_to_read_audio

        try:
            # return bool(MediaPermissionHandler.has_permission_to_access_audio_files())
            return bool(has_permission_to_read_audio())
        except Exception as error:
            logger.warning("audio access check failed: %s", error)
            return False

    @staticmethod
    def request_audio_access(callback):
        """Ask for the permission; ``callback(granted)`` reports the answer."""
        # if not on_android_platform():
        #     callback(True)
        if _requesting_audio_access:
            logger.warning("still requesting permission to read audio files")
            return

        # from android_notify.media.music.helper import MediaPermissionHandler

        # MediaPermissionHandler.ask_permission_to_access_audio_files(
        #     callback=callback)
        from android_notify.internal.permissions import ask_audio_permission

        ask_audio_permission(callback=callback, set_requesting_state=_set_requesting_audio_access)

    @staticmethod
    def has_notification_access():
        """Whether Android will show this app's notifications right now."""
        from android_notify.internal.permissions import has_notification_permission

        try:
            return bool(has_notification_permission())
        except Exception as error:
            logger.warning("notification permission check failed: %s", error)
            return True

    @staticmethod
    def request_notification_access(callback=None):
        """Ask for ``POST_NOTIFICATIONS`` (Android 13+; settings below that)."""
        from android_notify.internal.permissions import ask_notification_permission

        try:
            ask_notification_permission(callback=callback)
        except Exception as error:
            logger.warning("notification permission request failed: %s", error)
