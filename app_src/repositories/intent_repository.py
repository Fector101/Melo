import logging

from android_notify.config import get_python_activity_context, on_android_platform


logger = logging.getLogger("melo.intent")

UPDATE_ACTION = "open_update"



class IntentRepository:

    # These methods would be frequently used
    @staticmethod
    def get_intent():
        """returns intent object"""
        context = get_python_activity_context()
        intent = context.getIntent()
        return intent

    @staticmethod
    def get_extras_from_intent(intent):
        """returns extras object"""
        extras = intent.getExtras()
        return extras

    @staticmethod
    def get_value_from_extras(extras, key):
        """returns string value from extras object"""
        return extras.getString(key) or ""

    def read_update_intent(self, intent = None):
        """Read an update-notification tap.

        Returns ``{"action": "open_update", "version": "<version>"}`` when the
        intent carries the notification's extra, otherwise an empty dict. The
        extras are cleared afterward so a re-created activity does not replay
        the tap.
        """
        if not on_android_platform():
            return {}
        try:
            intent = intent or self.get_intent()
            if intent is None:
                return {}

            extras = self.get_extras_from_intent(intent) # ignore PyCharm warning intent has {getExtras}
            if extras is None:
                return {}

            action = self.get_value_from_extras(extras,"action")
            if action != UPDATE_ACTION:
                return {}
            version = self.get_value_from_extras(extras, "version")
            intent.replaceExtras(None)
            return {"action": action, "version": str(version)}
        except Exception as e:
            logger.exception(f"Could not read the update intent: {e}")
            return {}
