## How to inject code for hot refresh on debug APK 
```shell
 2045  adb push app_src/ui/widgets/layouts.py /data/local/tmp/layouts.py
 2046  adb shell "run-as org.wally.waller sh -c 'cp /data/local/tmp/layouts.py files/app/ui/widgets/layouts.py'"
 2047  adb shell am force-stop org.wally.waller && adb logcat -c && adb shell monkey -p org.wally.waller -c android.intent.category.LAUNCHER 1
 2048  adb logcat | grep python


```
```shell
PKG=io.github.fector101.melo
REL=android_notify/media/__init__.py
adb push app_src/$REL /data/local/tmp/tmp.py && \
adb shell "run-as $PKG sh -c 'cp /data/local/tmp/tmp.py files/app/$REL'" && \
adb shell "run-as $PKG sh -c 'rm -f files/app/${REL%.*}.pyc'" 2>/dev/null && \
adb shell am force-stop $PKG && adb logcat -c && \
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null && \
echo "launched; waiting for python logs..." && \
for i in $(seq 1 30); do adb logcat -d -s python 2>/dev/null | grep -q . && break; sleep 1; done && \
adb logcat -s python
```

## Background update check (Java)

The periodic check and its notification are Java (`app_src/android/src/`), the
intent handling is Python (`repositories/update_notification_repository.py`).
New files + `androidx.work:work-runtime` in `buildozer.spec` need a **full**
rebuild; `run-as` cannot hot-swap them.

The check is skipped while the app is in the foreground, so background the app
(Home) before waiting for the notification. "New version available" means
`versionName` (the spec version) is older than the latest tag.

```shell
PKG=io.github.fector101.melo
# update_endpoint.json is {"api_url": "http://127.0.0.1:8000/releases/latest"}
# and needs a cleartext-allowing network_security_config (gitignored) in the build.
# tests/device_self_update_test.py writes this file itself with adb reverse set up.
adb reverse tcp:8000 tcp:8000
adb push /tmp/update_endpoint.json /data/local/tmp/update_endpoint.json
adb shell "run-as $PKG sh -c 'cp /data/local/tmp/update_endpoint.json files/update_endpoint.json'"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS
```

Launch once; `WorkScheduler` sees the override and enqueues a one-time check
after 5 s. Press Home and watch:

```shell
adb logcat -s UpdateNotifier UpdateCheckWorker WorkScheduler
adb shell dumpsys jobscheduler | grep melo
adb shell dumpsys notification --noredact | grep -A5 update_channel
```

Reset the 7-day cooldown without wiping app data (a `pm clear` would also drop
the endpoint file and `POST_NOTIFICATIONS`; a force-stop is still needed to drop
the old notification):

```shell
adb shell "run-as $PKG rm -f shared_prefs/update_checker_prefs.xml" && \
adb shell am force-stop $PKG
```

Drive the tap path without waiting for a notification:

```shell
adb shell am start -n $PKG/org.kivy.android.PythonActivity \
  --es action open_update --es version 0.0.2
```

## Device test: background update notification

`tests/device_update_notification_test.py` runs the whole thing end to end
against the installed build: fake release server, endpoint push + cooldown
reset, foreground skip, WorkManager job/spec check, "not newer",
background notification, shade tap (`uiautomator`) opening the update screen,
and the cooldown. It deletes `files/update_endpoint.json` and
`shared_prefs/update_checker_prefs.xml` at start and end (never `pm clear`),
so it does not leave the app in a cooldown state.

```shell
cd /home/fabian/Documents/Melo
venv/bin/python tests/device_update_notification_test.py            # real shade tap
venv/bin/python tests/device_update_notification_test.py --intent-tap  # fallback
venv/bin/python tests/device_update_notification_test.py --keep     # leave state for poking
```

Needs the same debug install + cleartext `network_security_config.xml` build as
the self-update test, `POST_NOTIFICATIONS` granted (the script grants it), and an
awake phone. Two failure modes that look like "the check never ran":

- **`java.io.IOException: Cleartext HTTP traffic to 127.0.0.1 not permitted`** in
  `adb logcat -s UpdateNotifier` means the installed APK was built without
  `app_src/android/res/xml/network_security_config.xml` (the Java side uses
  `HttpURLConnection`, which honours the policy; Python's sockets do not). Check
  with `unzip -l <apk> | grep network_security_config` before blaming the code.
- **`INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match`** means the
  phone has a Melo signed with another key; `adb install -r` cannot replace it,
  uninstall first (that also drops the endpoint file and the permission, which
  the script sets up again).

MIUI ignores `cmd statusbar expand-notifications` sometimes (the script falls
back to a swipe), and `uiautomator dump` happily leaves a stale file behind when
the shade is animating - the script deletes the file first, waits for two
identical dumps and taps the card's clickable row, not the text. Notifications
are read from `dumpsys notification --noredact` filtered to `id=999` /
`channel=update_channel` (Melo's media notification would otherwise match
"Melo"). The WorkManager periodic interval is *not* a JobScheduler `PERIODIC:`
row: read `interval_duration` from `no_backup/androidx.work.workdb`.

MIUI/Doze can defer the 5 s override check, so the waits are 60 s; if a run
stalls, retry with `--timeout-scale 3` rather than assuming a code bug.

`--version` (default `0.0.2`) is the release the fake server serves; it must be
newer than the installed `versionName` for the notification scenarios.

## Important for track trace
```python
traceback.print_stack()
```
