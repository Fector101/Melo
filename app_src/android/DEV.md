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

Reset the 7-day cooldown (this also deletes the endpoint file and app data, so
re-run the endpoint push and `pm grant` afterwards):

```shell
adb shell pm clear $PKG
```

Drive the tap path without waiting for a notification:

```shell
adb shell am start -n $PKG/org.kivy.android.PythonActivity \
  --es action open_update --es version 0.0.2
```

## Important for track trace
```python
traceback.print_stack()
```
