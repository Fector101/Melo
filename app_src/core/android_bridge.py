"""Guarded access to the Android/JVM APIs the app needs.

``jnius`` only exists inside an Android build, so it is imported lazily and
every helper degrades to a no-op off Android. That keeps the repositories
importable on the desktop (and in the test suite).
"""

import logging
import traceback

from android_notify.config import on_android_platform

logger = logging.getLogger("melo.android")

autoclass = None
PythonJavaClass = None
java_method = None

if on_android_platform():
    try:
        from jnius import autoclass, PythonJavaClass, java_method
    except Exception as error:  # pragma: no cover - Android only
        logger.warning("jnius is unavailable: %s", error)
        autoclass = None
        PythonJavaClass = None
        java_method = None


if on_android_platform() and PythonJavaClass is not None:

    class AndroidUiRunnable(PythonJavaClass):
        """Runs a Python callable on the Android UI thread."""

        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        def __init__(self, fn):
            super().__init__()
            self.fn = fn

        @java_method("()V")
        def run(self):
            try:
                self.fn()
            except Exception:
                traceback.print_exc()

else:
    AndroidUiRunnable = None


_retriever_class = None
_retriever_loaded = False


def get_media_metadata_retriever():
    """The ``MediaMetadataRetriever`` class, or ``None`` off Android.

    The class is looked up once and cached: ``autoclass`` walks the JNI
    class loader, which is not free.
    """
    global _retriever_class, _retriever_loaded

    if not _retriever_loaded:
        _retriever_loaded = True
        if autoclass is not None:
            try:
                _retriever_class = autoclass(
                    "android.media.MediaMetadataRetriever")
            except Exception as error:  # pragma: no cover - Android only
                logger.warning("no MediaMetadataRetriever: %s", error)
                _retriever_class = None
    return _retriever_class


def run_on_ui_thread(callback):
    """Post ``callback`` to the Android UI thread.

    Returns ``True`` when the callback was handed over to Android, and
    ``False`` when the caller has to run it itself (desktop, no activity, or
    a failure while posting).
    """
    if AndroidUiRunnable is None:
        return False

    try:
        from android_notify.config import get_python_activity_context

        activity = get_python_activity_context()
        if activity is None:
            return False
        activity.runOnUiThread(AndroidUiRunnable(callback))
        return True
    except Exception as error:
        logger.debug("could not post to the Android UI thread: %s", error)
        return False
