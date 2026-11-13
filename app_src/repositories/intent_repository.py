"""The Android ``Intent`` the app was launched with (or received while running).

The update notification puts an ``action=open_update`` extra on its launch
intent; :class:`IntentRepository` is the only place that reads it. Everything
degrades to an empty dict off Android.
"""

import logging

from android_notify.config import get_python_activity_context, on_android_platform

logger = logging.getLogger("melo.intent")

UPDATE_ACTION = "open_update"


class IntentRepository:
    """Read the extras of the current activity's intent."""

    @staticmethod
    def get_intent():
        """The intent the activity was started with."""
        context = get_python_activity_context()
        intent = context.getIntent()
        return intent

    @staticmethod
    def get_extras_from_intent(intent):
        """The extras of ``intent`` (an Android ``Bundle``)."""
        return intent.getExtras()

    @staticmethod
    def get_value_from_extras(extras, key):
        """A string extra, or ``""`` when it is not there."""
        return extras.getString(key) or ""

    @staticmethod
    def read_update_intent(intent=None):
        """Read an update-notification tap.

        Returns ``{"action": "open_update", "version": "<version>"}`` when the
        intent carries the notification's extra, otherwise an empty dict. The
        extras are cleared afterward so a re-created activity does not replay
        the tap.
        """
        if not on_android_platform():
            return {}
        try:
            intent = intent or IntentRepository.get_intent()
            if intent is None:
                return {}
            extras = IntentRepository.get_extras_from_intent(intent)
            if extras is None:
                return {}
            action = IntentRepository.get_value_from_extras(extras, "action")
            if action != UPDATE_ACTION:
                return {}
            version = IntentRepository.get_value_from_extras(extras, "version")
            intent.replaceExtras(None)
            return {"action": action, "version": str(version)}
        except Exception as error:
            logger.exception("Could not read the update intent: %s", error)
            return {}
