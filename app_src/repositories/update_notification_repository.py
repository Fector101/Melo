"""The Android side of the update check: background work, notification, intents.

The check itself lives in Java (WorkManager + ``UpdateNotifier``) so a user who
has not opened Melo for a while still gets an "update available" notification
without the app running. This repository is the only Python side of it:

- schedule the Java work at startup;
- read the ``action=open_update`` extra the notification's tap carries;
- clear the notification once the update screen opens.

Everything degrades to a no-op off Android, and nothing here imports the update
UI: the modules that paint the update screen stay lazy.
"""

import logging

from android_notify.config import (get_package_name, get_python_activity_context,
                                   on_android_platform)
from core.android_bridge import autoclass
from repositories.intent_repository import IntentRepository

logger = logging.getLogger("melo.update")

#: The extra the Java notification puts on its launch intent.
UPDATE_ACTION = "open_update"

_java_classes = {}


def _context():
    """The Android activity (``None`` off Android)."""
    try:
        return get_python_activity_context()
    except Exception:
        logger.exception("Could not get the Android activity")
        return None


def _java_class(simple_name):
    """Look one Java class up once and keep it (autoclass is not free)."""
    if simple_name not in _java_classes:
        _java_classes[simple_name] = autoclass(f"{get_package_name()}.{simple_name}")
    return _java_classes[simple_name]


def schedule_background_check():
    """Ask the Java ``WorkScheduler`` for the periodic check plus the first run."""
    if not on_android_platform() or autoclass is None:
        return False
    context = _context()
    if context is None:
        return False
    try:
        _java_class("WorkScheduler").scheduleUpdateCheck(context)
        logger.info("Background update check scheduled")
        return True
    except Exception as e:
        logger.exception(f"Could not schedule the background update check: {e}")
        return False



def bind_update_intents(callback):
    """Call ``callback(payload)`` when a notification tap arrives while running."""
    if not on_android_platform() or callback is None:
        return False
    try:
        from android import activity  # type: ignore

        def on_new_intent(intent):
            payload = IntentRepository.read_update_intent(intent)
            if payload:
                callback(payload)

        activity.bind(on_new_intent=on_new_intent)
        logger.info("Update notification intents bound")
        return True
    except Exception:
        logger.exception("Could not bind the update notification listener")
        return False


def cancel_notification():
    """Remove the background notification (the update screen is open)."""
    if not on_android_platform() or autoclass is None:
        return False
    context = _context()
    if context is None:
        return False
    try:
        _java_class("UpdateNotifier").cancel(context)
        return True
    except Exception:
        logger.exception("Could not cancel the update notification")
        return False
