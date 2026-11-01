"""The Python side of the Java background update check.

Only the intent payload and the off-Android no-ops are testable here: the Java
worker, the notification and the periodic scheduling need a device.
"""

import repositories.update_notification_repository as notifications


class FakeExtras:
    """Just enough of an Android ``Bundle`` for the intent reader."""

    def __init__(self, values):
        self.values = dict(values)

    def getString(self, key, default=None):
        value = self.values.get(key)
        return default if value is None else value


class FakeIntent:
    """Just enough of an Android ``Intent`` for the intent reader."""

    def __init__(self, values=None):
        self.extras = FakeExtras(values or {})
        self.cleared = False

    def getExtras(self):
        return self.extras

    def replaceExtras(self, value):
        assert value is None
        self.cleared = True


def test_reads_the_update_action_and_version(monkeypatch):
    monkeypatch.setattr(notifications, "on_android_platform", lambda: True)
    intent = FakeIntent({"action": "open_update", "version": "0.0.2"})

    payload = notifications.read_update_intent(intent)

    assert payload == {"action": "open_update", "version": "0.0.2"}
    assert intent.cleared is True


def test_ignores_other_intents_and_keeps_their_extras(monkeypatch):
    monkeypatch.setattr(notifications, "on_android_platform", lambda: True)
    intent = FakeIntent({"action": "something_else", "version": "0.0.2"})

    assert notifications.read_update_intent(intent) == {}
    assert intent.cleared is False


def test_an_intent_without_extras_is_ignored(monkeypatch):
    monkeypatch.setattr(notifications, "on_android_platform", lambda: True)
    intent = FakeIntent()

    assert notifications.read_update_intent(intent) == {}
    assert intent.cleared is False


def test_a_version_is_optional(monkeypatch):
    monkeypatch.setattr(notifications, "on_android_platform", lambda: True)
    intent = FakeIntent({"action": "open_update"})

    assert notifications.read_update_intent(intent) == {
        "action": "open_update", "version": ""}


def test_the_java_hooks_are_no_ops_off_android(monkeypatch):
    monkeypatch.setattr(notifications, "on_android_platform", lambda: False)
    intent = FakeIntent({"action": "open_update", "version": "0.0.2"})

    assert notifications.read_update_intent(intent) == {}
    assert intent.cleared is False
    assert notifications.schedule_background_check() is False
    assert notifications.cancel_notification() is False
    assert notifications.bind_update_intents(lambda payload: None) is False
