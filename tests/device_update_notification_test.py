#!/usr/bin/env python3
"""Drive Melo's Java background update check and its notification on a phone.

What it does
------------
1. points the installed debug build at a fake release served from this machine
   (``adb reverse`` + ``files/update_endpoint.json``),
2. checks the worker runs but posts nothing while Melo is in front,
3. checks a release that is not newer posts nothing (the numeric compare),
4. backgrounds Melo, waits for the WorkManager notification and reads it back
   from ``dumpsys notification`` (id, channel, importance, title, text) and from
   the app's SharedPreferences (``last_notified_timestamp``),
5. taps the notification in the real shade (``uiautomator`` finds it by its
   text) and checks Melo comes to the front, logs the payload, renders the
   update modal and cancels the notification,
6. checks the 7 day cooldown suppresses a second notification.

What it cannot check
--------------------
* a real week passing - the 7 day interval is read from WorkManager's own
  database instead (``no_backup/androidx.work.workdb``)
* the download side of the update (``device_self_update_test.py`` covers it)

Requirements
------------
* a debug build with the Java check installed (``app_src/android/src`` +
  ``androidx.work``). A build made before that feature fails the first check
  with a "rebuild" hint.
* the same cleartext-allowing build the download test needs
  (``app_src/android/res/xml/network_security_config.xml``, gitignored), or the
  phone refuses ``http://127.0.0.1``
* an unlocked, awake phone
* notification permission: the script grants ``POST_NOTIFICATIONS`` itself

Usage
-----
    venv/bin/python tests/device_update_notification_test.py
    venv/bin/python tests/device_update_notification_test.py --intent-tap
    venv/bin/python tests/device_update_notification_test.py --keep

``--intent-tap`` skips the shade and starts Melo with the same extras the
notification carries; use it when a ROM hides notifications from
``uiautomator``, or to tell "the payload works" apart from "the tap works".

The endpoint file and the cooldown prefs are removed on the way out unless
``--keep`` says otherwise - leaving the prefs behind means no notification for
seven days. Nothing here touches git or buildozer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from device_screen import Adb, AdbError, Rect  # noqa: E402
from device_self_update_test import (  # noqa: E402
    ACTIVITY,
    ENDPOINT_FILE,
    PACKAGE,
    FakeRelease,
    Report,
    check_logs,
    check_preflight,
    restart_app,
    wait_for,
    wait_modal,
)
from device_self_update_test import TestFailure as Failure  # noqa: E402

# --------------------------------------------------------------------------- #
# What the Java side writes (keep in sync with app_src/android/src)           #
# --------------------------------------------------------------------------- #
NOTIFICATION_ID = 999
CHANNEL_ID = "update_channel"
CHANNEL_IMPORTANCE = 3              # NotificationManager.IMPORTANCE_DEFAULT
TITLE = "New version available"
TEXT = "v{} is ready. Tap to update."
PREFS_FILE = "shared_prefs/update_checker_prefs.xml"
WORKER = f"{PACKAGE}.UpdateCheckWorker"
WORK_DB = "no_backup/androidx.work.workdb"
SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
OVERRIDE_DELAY_MS = 5_000

#: Log lines and notification bits that prove each step happened.
SCHEDULED = "Background update check scheduled"
FOREGROUND_SKIP = "App is in the foreground, skipping"
SENT = "Notification sent for v"
ALREADY_LATEST = "Already on latest version"
COOLDOWN = "Cooldown active, skipping"
TAPPED = "Update notification tapped"   # the payload follows; no colon asserted

LOG_TAGS = (
    "python",
    "UpdateEndpoints",
    "UpdateNotifier",
    "UpdateCheckWorker",
    "WorkScheduler",
    "WM-SystemJobScheduler",
    "WM-WorkerWrapper",
    "WM-Processor",
)

UI_DUMP = "/data/local/tmp/melo_notification_ui.xml"


def notification_needles(offered: str) -> tuple[str, ...]:
    """Text only the update notification has (Melo also posts a media one)."""
    return (TEXT.format(offered), TITLE)


# --------------------------------------------------------------------------- #
# Reading the phone                                                           #
# --------------------------------------------------------------------------- #
def journal(adb: Adb, lines: int = 4000) -> str:
    """Logcat for the Python app plus the Java update-check tags."""
    specs = [f"{tag}:V" for tag in LOG_TAGS]
    return adb.run("logcat", "-d", "-t", str(lines), "-s", *specs, check=False)


def wait_for_text(adb: Adb, needle: str, timeout: float, what: str) -> str:
    return wait_for(lambda: needle if needle in journal(adb) else None,
                    timeout, what)


def live_notifications(adb: Adb) -> str:
    """Only the current ``Notification List`` section of the dump."""
    dump = adb.shell("dumpsys notification --noredact")
    start = dump.find("Notification List:")
    if start < 0:
        return ""
    end = len(dump)
    for marker in ("\n  mMaxPackageEnqueueRate", "\n  Notification attention state:"):
        index = dump.find(marker, start)
        if index > 0:
            end = min(end, index)
    return dump[start:end]


def notification_blocks(adb: Adb) -> list[str]:
    """The live records that belong to Melo (there may be more than one)."""
    section = live_notifications(adb)
    needle = f"pkg={PACKAGE} user="
    blocks = re.split(r"NotificationRecord\(0x", section)
    return [block for block in blocks if needle in block]


def update_notification_blocks(adb: Adb) -> list[str]:
    """Only the update notification; Melo also posts its media player."""
    records = []
    for block in notification_blocks(adb):
        header = block.split("\n", 1)[0]
        if (re.search(rf"\bid={NOTIFICATION_ID}\b", header)
                or f"channel={CHANNEL_ID}" in header):
            records.append(block)
    return records


HEADER = re.compile(
    r"pkg=(\S+) user=\S+ id=(\d+) tag=\S+ importance=(\d+).*?channel=([\w.-]+)")
CHANNEL = re.compile(r"mId='([^']+)',.*?mImportance=(\d+)")


def _string_extra(block: str, key: str) -> str:
    marker = f"{key}=String ("
    index = block.find(marker)
    if index < 0:
        return ""
    return block[index + len(marker):].split(")\n", 1)[0].strip()


def notification_details(adb: Adb) -> dict | None:
    """What the update notification currently says, or ``None`` if it is gone."""
    blocks = update_notification_blocks(adb)
    if not blocks:
        return None
    block = blocks[0]
    header = HEADER.search(block)
    if header is None:
        return None
    return {
        "id": int(header.group(2)),
        "importance": int(header.group(3)),
        "channel": header.group(4),
        "title": _string_extra(block, "android.title"),
        "text": _string_extra(block, "android.text"),
        "content_intent": "contentIntent=PendingIntent{" in block,
        "channels": [{"id": match[0], "importance": int(match[1])}
                     for match in CHANNEL.findall(block)],
    }


def read_prefs(adb: Adb) -> dict:
    """``update_checker_prefs.xml`` as a dict (empty if the file is absent)."""
    xml = adb.run_as(PACKAGE, f"cat {PREFS_FILE}", check=False)
    values: dict[str, str] = {}
    for match in re.finditer(
            r'<(\w+)\s+name="([^"]+)"\s+value="([^"]*)"\s*/>', xml):
        values[match.group(2)] = match.group(3)
    for match in re.finditer(
            r'<(\w+)\s+name="([^"]+)"\s*>\s*([^<]*?)\s*</\1>', xml):
        values.setdefault(match.group(2), match.group(3))
    return values


def notification_permission(adb: Adb) -> str:
    """``allow``/``ignore``/``deny`` from appops (explicit op beats the default)."""
    output = adb.shell(f"cmd appops get {PACKAGE} POST_NOTIFICATION", check=False)
    default = ""
    explicit = ""
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("default mode:"):
            default = line.split(":", 1)[1].strip().lower()
        elif "POST_NOTIFICATION" in line:
            explicit = line.rsplit(":", 1)[-1].strip().lower()
    return explicit or default


def ensure_notification_permission(adb: Adb, report: Report) -> None:
    report.step("notification permission")
    current = notification_permission(adb)
    report.info(f"POST_NOTIFICATION is {current or 'unknown'} before the test")
    if current != "allow":
        adb.shell(f"pm grant {PACKAGE} android.permission.POST_NOTIFICATIONS",
                  check=False)
        current = notification_permission(adb)
    if current != "allow":
        adb.shell(f"cmd appops set {PACKAGE} POST_NOTIFICATION allow",
                  check=False)
        current = notification_permission(adb)
    report.check("Melo may post notifications", current == "allow",
                 f"POST_NOTIFICATION={current or 'unknown'}")


def screen_size(adb: Adb) -> tuple[int, int]:
    output = adb.shell("wm size")
    match = (re.search(r"Override size: (\d+)x(\d+)", output)
             or re.search(r"Physical size: (\d+)x(\d+)", output))
    return (int(match.group(1)), int(match.group(2))) if match else (720, 1600)


def background_app(adb: Adb, timeout: float = 12) -> bool:
    """Press Home until Melo is really not the resumed activity.

    The app takes a moment to come up, so one Home press can land before the
    activity does; the worker then sees a foreground app and skips.
    """
    adb.key("KEYCODE_HOME")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        activity = adb.top_activity()
        if PACKAGE not in activity:
            return True
        adb.key("KEYCODE_HOME")
    return PACKAGE not in adb.top_activity()


def wait_foreground(adb: Adb, timeout: float) -> str | None:
    def read():
        activity = adb.top_activity()
        return activity if PACKAGE in activity else None

    try:
        return wait_for(read, timeout, "Melo in the foreground")
    except Failure:
        return None


# --------------------------------------------------------------------------- #
# Finding the notification in the shade                                       #
# --------------------------------------------------------------------------- #
def dump_ui(adb: Adb) -> str:
    """A fresh dump, or ``""`` when the screen was not idle.

    ``uiautomator`` leaves the previous file in place when it cannot take a
    dump (a shade animation is enough), so the file is removed first: a stale
    dump means stale bounds, and tapping those closes the shade instead of
    opening the notification.
    """
    adb.shell(f"rm -f {UI_DUMP}", check=False)
    adb.shell(f"uiautomator dump {UI_DUMP}", check=False)
    xml = adb.shell(f"cat {UI_DUMP}", check=False)
    return xml if "<hierarchy" in xml else ""


BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
TEXTS = re.compile(r'text="([^"]+)"')


def _rect(node) -> Rect | None:
    match = BOUNDS.search(node.get("bounds", ""))
    if match is None:
        return None
    rect = Rect(*(int(value) for value in match.groups()))
    return rect if rect.width > 0 and rect.height > 0 else None


def find_node_bounds(xml: str, needles: tuple[str, ...]) -> Rect | None:
    """The tap target of the node whose text contains a needle.

    The notification's TextViews are not clickable; the row around them is
    (SystemUI's ``FrameLayout``), and its centre is a much steadier target
    than the text, which moves while the shade settles.
    """
    if not xml:
        return None
    wanted = [needle.lower() for needle in needles if needle]
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    parents = {child: parent for parent in root.iter() for child in parent}

    text_rect: Rect | None = None
    row_rect: Rect | None = None
    for node in root.iter("node"):
        text = " ".join(filter(None, (node.get("text"), node.get("content-desc"))))
        if not any(needle in text.lower() for needle in wanted):
            continue
        rect = _rect(node)
        if rect is None:
            continue
        if text_rect is None or rect.area < text_rect.area:
            text_rect = rect
        parent = parents.get(node)
        while parent is not None:
            target = _rect(parent)
            if parent.get("clickable") == "true" and target is not None:
                if row_rect is None or target.area > row_rect.area:
                    row_rect = target
                break
            parent = parents.get(parent)
    return row_rect or text_rect


def shade_texts(adb: Adb, limit: int = 12) -> list[str]:
    """Short text labels currently on screen (for failure reports)."""
    xml = dump_ui(adb)
    found = [html_text.strip() for html_text in TEXTS.findall(xml)]
    return [item[:36] for item in found if item][:limit]


def shade_target(adb: Adb, needles: tuple[str, ...], timeout: float) -> Rect | None:
    """Wait until the shade has settled and the notification is tappable."""
    deadline = time.time() + timeout
    previous: Rect | None = None
    while time.time() < deadline:
        rect = find_node_bounds(dump_ui(adb), needles)
        if rect is not None and rect == previous:
            return rect
        previous = rect
        time.sleep(0.4)
    return previous


def open_shade(adb: Adb, needles: tuple[str, ...], timeout: float = 20.0) -> Rect | None:
    adb.shell("cmd statusbar expand-notifications", check=False)
    rect = shade_target(adb, needles, timeout / 2)
    if rect is not None:
        return rect
    # Some ROMs ignore the statusbar command; pull the shade down by hand.
    width, height = screen_size(adb)
    adb.swipe(width // 2, 2, width // 2, int(height * 0.7), 250)
    return shade_target(adb, needles, timeout / 2)


# --------------------------------------------------------------------------- #
# The scenarios                                                               #
# --------------------------------------------------------------------------- #
def push_endpoint(adb: Adb, server: FakeRelease, report: Report) -> None:
    report.step("test plumbing")
    adb.reverse(server.port)
    report.check("adb reverse tunnel", True,
                 f"tcp:{server.port} -> host tcp:{server.port}")

    # A leftover cooldown from an earlier run would suppress the notification,
    # and a leftover endpoint file would make the "no override" branch behave
    # differently. Start from the same state a fresh debug build has.
    adb.force_stop(PACKAGE)
    adb.run_as(PACKAGE, f"rm -f files/{ENDPOINT_FILE} {PREFS_FILE}", check=False)
    left = adb.run_as(PACKAGE, f"ls files/{ENDPOINT_FILE} {PREFS_FILE}",
                      check=False).strip()
    report.check("the app starts without a cooldown or an old override",
                 not left, left or "clean")

    payload = json.dumps({
        "api_url": f"http://127.0.0.1:{server.port}/releases/latest",
    }).encode()
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as handle:
        handle.write(payload)
        local = handle.name
    try:
        adb.run("push", local, "/data/local/tmp/melo_notification_endpoint.json")
    finally:
        os.unlink(local)
    adb.run_as(PACKAGE,
               "cp /data/local/tmp/melo_notification_endpoint.json "
               f"files/{ENDPOINT_FILE}")
    adb.run("shell", "rm -f /data/local/tmp/melo_notification_endpoint.json",
            check=False)
    written = adb.run_as(PACKAGE, f"cat files/{ENDPOINT_FILE}", check=False)
    report.check("the endpoint override points at this machine",
                 '"api_url"' in written and str(server.port) in written,
                 f"127.0.0.1:{server.port}")
    report.info("the Java check only reads api_url; base_url stays untouched")


def check_foreground_skip(adb: Adb, report: Report, scale: float) -> None:
    report.step("the worker runs, but not while Melo is in front")
    adb.clear_logs()
    restart_app(adb)
    try:
        wait_for_text(adb, SCHEDULED, 25 * scale,
                      "the background check to be scheduled")
    except Failure as error:
        raise Failure(
            f"{error}. The installed build predates the Java update check: "
            "rebuild (app_src/android/src + androidx.work), then reinstall."
        ) from error
    report.check("the installed build schedules the Java check", True, SCHEDULED)

    wait_for_text(adb, FOREGROUND_SKIP, 45 * scale,
                  "the worker to skip the foreground app")
    report.check("the worker skipped a foreground Melo", True, FOREGROUND_SKIP)
    report.check("nothing was posted", SENT not in journal(adb),
                 "the update UI owns the foreground")
    details = notification_details(adb)
    report.check("no update notification is in the shade", details is None,
                 "clean")


def work_specs(adb: Adb) -> list[dict]:
    """The WorkManager specs for our worker, read from its own database.

    WorkManager stores periodic work as a one-off JobScheduler job that it
    reschedules itself, so ``dumpsys jobscheduler`` cannot show the 7 day
    interval - the WorkSpec row can. The database is in ``no_backup`` and is in
    WAL mode, so the ``-wal``/``-shm`` files have to come along.
    """
    folder = Path(tempfile.mkdtemp(prefix="melo-workdb-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            blob = adb.run("exec-out", "run-as", PACKAGE, "cat",
                           WORK_DB + suffix, binary=True, check=False)
            (folder / f"workdb{suffix}").write_bytes(blob)
        connection = sqlite3.connect(f"file:{folder / 'workdb'}?mode=ro",
                                     uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT state, initial_delay, interval_duration FROM WorkSpec "
                "WHERE worker_class_name = ?", (WORKER,)).fetchall()
        finally:
            connection.close()
        return [dict(row) for row in rows]
    except (sqlite3.Error, OSError) as error:
        raise Failure(f"could not read the WorkManager database: {error}") from error
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check_work_specs(adb: Adb, report: Report, scale: float) -> None:
    report.step("the 7 day work and the override check are in WorkManager")

    def read():
        rows = work_specs(adb)
        periodic = [row for row in rows
                    if row["interval_duration"] == SEVEN_DAYS_MS]
        override = [row for row in rows
                    if row["initial_delay"] == OVERRIDE_DELAY_MS]
        return (periodic, override) if periodic and override else None

    periodic, override = wait_for(read, 25 * scale, "the WorkManager specs")
    report.check("the periodic check runs every 7 days", True,
                 f"interval_duration={periodic[0]['interval_duration']:,} ms")
    report.check("the override check runs 5 s after launch", True,
                 f"initial_delay={override[0]['initial_delay']:,} ms")

    def finished():
        return next((row for row in work_specs(adb)
                     if row["initial_delay"] == OVERRIDE_DELAY_MS
                     and row["state"] == 2), None)

    done = wait_for(finished, 15 * scale,
                    "the override check to be marked SUCCEEDED")
    report.check("the override check already ran", True,
                 f"state={done['state']} (2 = SUCCEEDED)")


def check_not_newer(adb: Adb, server: FakeRelease, report: Report,
                    installed: str, scale: float) -> None:
    report.step("a release that is not newer posts nothing")
    tag = server.set_version(installed)
    adb.clear_logs()
    restart_app(adb)
    wait_for_text(adb, SCHEDULED, 25 * scale,
                  "the background check to be scheduled")
    report.check("Melo is in the background", background_app(adb),
                 f"top activity {adb.top_activity().split(' ')[0][:60] or 'none'}")
    wait_for_text(adb, ALREADY_LATEST, 60 * scale,
                  "the worker to compare versions")
    report.check("the worker compared against the installed version", True,
                 f"latest={tag}, installed={installed}")
    report.check("nothing was posted", SENT not in journal(adb), "no new release")
    report.check("no update notification is in the shade",
                 notification_details(adb) is None, "clean")
    stamp = read_prefs(adb).get("last_notified_timestamp")
    report.check("the cooldown timestamp was not saved", stamp in (None, "", "0"),
                 f"last_notified_timestamp={stamp}")


def check_background_notification(adb: Adb, server: FakeRelease, report: Report,
                                  offered: str, scale: float) -> None:
    report.step("a backgrounded Melo gets the notification")
    server.set_version(offered)
    adb.clear_logs()
    restart_app(adb)
    wait_for_text(adb, SCHEDULED, 30 * scale, "the check to be scheduled")
    report.check("Melo is in the background", background_app(adb),
                 f"top activity {adb.top_activity().split(' ')[0][:60] or 'none'}")

    wait_for_text(adb, SENT + offered, 60 * scale, "the notification")
    report.check("the worker posted the notification", True, SENT + offered)

    details = wait_for(lambda: notification_details(adb), 15,
                       "the notification in dumpsys notification")
    report.check("it is Melo's update notification",
                 details["id"] == NOTIFICATION_ID and details["channel"] == CHANNEL_ID,
                 f"id={details['id']} channel={details['channel']}")
    report.check("the channel is IMPORTANCE_DEFAULT",
                 details["importance"] == CHANNEL_IMPORTANCE,
                 f"record importance={details['importance']}")
    report.check("the title says a new version is available",
                 details["title"] == TITLE, repr(details["title"]))
    report.check("the text names the served version",
                 details["text"] == TEXT.format(offered), repr(details["text"]))
    configured = [item for item in details["channels"] if item["id"] == CHANNEL_ID]
    report.check("the channel exists as a default-importance channel",
                 any(item["importance"] == CHANNEL_IMPORTANCE
                     for item in configured),
                 str(details["channels"]))
    report.check("tapping it would launch an activity",
                 details["content_intent"], "contentIntent is a PendingIntent")

    prefs = read_prefs(adb)
    report.check("the override took the 5 s branch, not the 60 s first-install one",
                 prefs.get("first_check_scheduled") is None,
                 f"first_check_scheduled={prefs.get('first_check_scheduled')}")
    stamp = wait_for(
        lambda: int(read_prefs(adb).get("last_notified_timestamp", "0") or 0)
        or None, 10, "the cooldown timestamp in shared_prefs")
    report.check("the cooldown timestamp was saved", stamp > 0, f"{stamp} ms")

    time.sleep(3)
    report.check("only one update notification exists",
                 len(update_notification_blocks(adb)) == 1,
                 f"{len(update_notification_blocks(adb))} record(s)")


def tap_shade_notification(adb: Adb, report: Report, offered: str,
                           timeout: float) -> str | None:
    """Open the shade and tap the card; retry with a fresh shade each time."""
    needles = notification_needles(offered)
    attempts = 3
    for attempt in range(1, attempts + 1):
        rect = open_shade(adb, needles)
        if rect is None:
            # Somebody (usually the person holding the phone) may have tapped
            # the notification before this synthetic tap got to it.
            if PACKAGE in adb.top_activity() and TAPPED in journal(adb):
                return "the notification was already tapped; Melo is in front"
            if attempt == 1:
                raise Failure(
                    "the notification is not visible to uiautomator in the "
                    f"shade (looked for {needles}). Top activity "
                    f"{adb.top_activity()[:60] or 'none'}; shade texts "
                    f"{shade_texts(adb)}. Rerun with --intent-tap if this ROM "
                    "hides notifications from the accessibility tree.")
            report.info(f"attempt {attempt}: the card is no longer in the shade")
            return None
        adb.tap(*rect.center)
        activity = wait_foreground(adb, timeout)
        adb.shell("cmd statusbar collapse", check=False)
        if activity is not None:
            return f"tapped the card at {rect.center} (attempt {attempt})"
        report.info(f"attempt {attempt}: the tap at {rect.center} did not open "
                    "Melo; reopening the shade")
        adb.shell("cmd statusbar collapse", check=False)
        time.sleep(1.0)
    return None


def check_tap(adb: Adb, report: Report, offered: str, intent_tap: bool,
              scale: float) -> None:
    report.step("the notification tap opens the update screen")
    if intent_tap:
        adb.shell(f"am start -n {ACTIVITY} --es action open_update "
                  f"--es version {offered}")
        how = "--intent-tap with the notification's extras"
        activity = wait_foreground(adb, 15 * scale)
        report.check("Melo came to the front", activity is not None,
                     how if activity else f"{how}, top activity "
                     f"{adb.top_activity()[:60] or 'none'}")
    else:
        how = tap_shade_notification(adb, report, offered, 15 * scale)
        report.check("the shade tap opened Melo", how is not None,
                     how or f"top activity {adb.top_activity()[:60] or 'none'}")
        if how is None:
            raise Failure(
                "tapping the notification card did not open Melo after 3 "
                "tries. Rerun with --intent-tap to test the payload only.")
        report.info(f"tap: {how}")

    wait_for_text(adb, TAPPED, 15 * scale, "the tap handler's log line")
    report.check("the Python side received the tap", True, TAPPED)
    report.check("the payload carries the offered version",
                 f"'version': '{offered}'" in journal(adb),
                 f"version={offered}")

    snap = wait_modal(adb, 60 * scale)
    report.check("the update screen rendered", True, snap.describe())
    details = notification_details(adb)
    report.check("opening the update screen cancelled the notification",
                 details is None, "no record left")


def check_cooldown(adb: Adb, report: Report, scale: float) -> None:
    report.step("the 7 day cooldown suppresses a second notification")
    stamp_before = read_prefs(adb).get("last_notified_timestamp")
    adb.clear_logs()
    restart_app(adb)
    wait_for_text(adb, SCHEDULED, 30 * scale, "the check to be scheduled")
    report.check("Melo is in the background", background_app(adb),
                 f"top activity {adb.top_activity().split(' ')[0][:60] or 'none'}")
    wait_for_text(adb, COOLDOWN, 60 * scale, "the cooldown gate")
    report.check("the worker hit the cooldown", True, COOLDOWN)
    report.check("nothing was posted again", SENT not in journal(adb),
                 "one notification per week")
    report.check("the cooldown timestamp did not move",
                 read_prefs(adb).get("last_notified_timestamp") == stamp_before,
                 f"{stamp_before} -> {read_prefs(adb).get('last_notified_timestamp')}")


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def dummy_artifact() -> Path:
    """Something for FakeRelease to serve; this test never downloads it."""
    handle = tempfile.NamedTemporaryFile("wb", suffix=".apk", delete=False)
    handle.write(b"Melo notification test placeholder\n")
    handle.close()
    return Path(handle.name)


def run(args: argparse.Namespace) -> int:
    report = Report()
    adb = Adb(serial=args.serial, executable=args.adb)
    artifact = dummy_artifact()
    server = FakeRelease(artifact, args.version, port=args.port, rate=0).start()
    print(f"Melo background update notification test\n"
          f"  adb     : {adb.executable}\n"
          f"  release : {server.tag} on 127.0.0.1:{server.port}\n"
          f"  tap     : {'intent' if args.intent_tap else 'notification shade'}")

    try:
        ensure_notification_permission(adb, report)
        installed = check_preflight(adb, report, args.version)
        push_endpoint(adb, server, report)
        check_foreground_skip(adb, report, args.timeout_scale)
        check_work_specs(adb, report, args.timeout_scale)
        check_not_newer(adb, server, report, installed, args.timeout_scale)
        check_background_notification(adb, server, report, args.version,
                                      args.timeout_scale)
        check_tap(adb, report, args.version, args.intent_tap, args.timeout_scale)
        check_logs(adb, report)
        check_cooldown(adb, report, args.timeout_scale)
        check_logs(adb, report)
    except Failure:
        print("\nlast log lines:")
        for line in journal(adb).strip().splitlines()[-25:]:
            print(f"  {line[:160]}")
        raise
    finally:
        adb.shell("cmd statusbar collapse", check=False)
        try:
            adb.force_stop(PACKAGE)
        except AdbError:
            pass  # the device vanished; the failure above is the useful one
        adb.reverse_remove(server.port)
        adb.shell(f"rm -f {UI_DUMP}", check=False)
        if not args.keep:
            adb.run_as(
                PACKAGE,
                f"rm -f files/{ENDPOINT_FILE} {PREFS_FILE}", check=False)
            print("\ncleaned the device (endpoint override + cooldown prefs); "
                  "use --keep to leave them")
        server.stop()
        artifact.unlink(missing_ok=True)
    return report.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end test of Melo's Java background update "
                    "notification on a connected Android phone.")
    parser.add_argument("--version", default="0.0.2",
                        help="version to advertise; must be newer than the app")
    parser.add_argument("--serial", default=None, help="adb serial")
    parser.add_argument("--adb", default=None, help="path to adb")
    parser.add_argument("--port", type=int, default=8000,
                        help="host port for the fake release (0 = random)")
    parser.add_argument("--intent-tap", action="store_true",
                        help="start Melo with the notification's extras instead "
                             "of tapping the real notification")
    parser.add_argument("--keep", action="store_true",
                        help="leave the endpoint override and the cooldown "
                             "prefs on the phone (no notification for 7 days)")
    parser.add_argument("--timeout-scale", type=float, default=1.0,
                        help="multiply the long timeouts (slow phone/build)")
    args = parser.parse_args(argv)

    try:
        return run(args)
    except Failure as error:
        print(f"\nFAILED: {error}")
        return 1
    except AdbError as error:
        print(f"\nadb error: {error}")
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
