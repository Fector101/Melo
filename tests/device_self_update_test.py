#!/usr/bin/env python3
"""Drive Melo's self-update on a connected Android phone and check every step.

What it does
------------
1. serves a fake GitHub release from this machine (the debug build only needs
   an ``adb reverse`` tunnel and ``files/update_endpoint.json``),
2. launches the installed debug build and waits for the update modal,
3. taps Download, watches the partial file grow, taps Cancel and checks the
   partial is kept,
4. taps Download again and checks the resume went out as ``Range``/206,
5. waits for the full APK, taps Install and checks the installer got a
   ``content://`` FileProvider URI (and, unless ``--skip-install``, that the
   package really was replaced),
6. relaunches, checks that a complete cached APK jumps straight to "Install"
   with no network, then checks "Later" -> chip -> reopen does not re-check,
7. fails on any Python traceback in logcat.

Everything is read back from the framebuffer (see ``device_screen.py``), from
logcat and from the app's private files - never by looking at an image.

Requirements
------------
* a debug build already installed (``adb install -r bin/melo-*-debug.apk``)
* an unlocked, awake phone (the script refuses to run on a locked screen:
  Kivy cannot create its surface and every screenshot would be black)
* the APK that build produced, to serve as the "new" version
* someone to approve the MIUI / Play Protect prompt if the ROM shows one: the
  script waits up to 120 s (``--timeout-scale``) and says so while waiting

Usage
-----
    venv/bin/python tests/device_self_update_test.py
    venv/bin/python tests/device_self_update_test.py --rate 0 --skip-install
    venv/bin/python tests/device_self_update_test.py --apk /path/to.apk --keep

The endpoint file and the downloaded APKs are removed on the way out unless
``--keep`` says otherwise. Nothing here touches git or buildozer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from device_screen import Adb, AdbError, Frame, Rect, hex_color  # noqa: E402

# --------------------------------------------------------------------------- #
# What the app looks like (ui/theme.py -> device pixels)                      #
# --------------------------------------------------------------------------- #
PACKAGE = "io.github.fector101.melo"
ACTIVITY = f"{PACKAGE}/org.kivy.android.PythonActivity"
ENDPOINT_FILE = "update_endpoint.json"

BG = (28, 31, 38)          # UPDATE_BG, the modal background
CARD = (36, 38, 46)        # UPDATE_CARD_BG, the big card
LINE = (56, 61, 71)        # UPDATE_LINE, secondary pill outline
ACCENT = (92, 184, 240)    # enabled pill
ACCENT_DIM = (56, 89, 114)  # ACCENT_DIM over the card = downloading/installing
OK = (77, 199, 115)        # status text in the ready state
DANGER = (242, 115, 102)   # status text in the failed state

#: "Install" (63 px) is about a third of "Download update" (191 px) at 720 px
#: wide; anything under this ratio is the short label.
SHORT_LABEL_RATIO = 0.35

#: A pill is wider than a chip and sits below the top of the screen.
MIN_PILL_WIDTH = 240
MIN_PILL_HEIGHT = 40
MIN_PILL_TOP = 0.15  # fraction of the screen height


class TestFailure(RuntimeError):
    """A check failed; the run stops (some steps cannot continue)."""


# --------------------------------------------------------------------------- #
# Reporting                                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)

    def step(self, title: str) -> None:
        print(f"\n== {title} ==")

    def check(self, name: str, ok: bool, detail: str = "",
              fatal: bool = True) -> bool:
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}" + (f"  ({detail})" if detail else ""))
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(name)
            if fatal:
                raise TestFailure(f"{name}: {detail}" if detail else name)
        return ok

    def skip(self, name: str, why: str) -> None:
        print(f"  SKIP  {name}  ({why})")
        self.skipped += 1

    def info(self, text: str) -> None:
        print(f"        {text}")

    def summary(self) -> int:
        print(f"\n== summary ==\n  {self.passed} passed, {self.failed} failed, "
              f"{self.skipped} skipped")
        for name in self.failures:
            print(f"  failed: {name}")
        return 0 if not self.failed else 1


# --------------------------------------------------------------------------- #
# Fake release server                                                         #
# --------------------------------------------------------------------------- #
class FakeRelease:
    """A minimal stand-in for the two GitHub endpoints the updater calls.

    Records every request so the test can prove that a step did *not* touch
    the network (much stronger than grepping logs).
    """

    RANGE = re.compile(r"bytes=(\d+)-")

    def __init__(self, apk: Path, version: str, port: int = 0, rate: int = 0):
        self.apk = Path(apk)
        self.size = self.apk.stat().st_size
        self.tag = "v" + version.lstrip("v")
        self.rate = max(0, int(rate))
        self.requests: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self._server.server_address[1]
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------- #
    def start(self) -> "FakeRelease":
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-release", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- data ------------------------------------------------------------ #
    def release(self) -> dict:
        assets = [
            {
                "name": f"melo-{self.tag}-{abi}.apk",
                "size": self.size,
                "download_count": 0,
                "updated_at": "2026-10-26T00:00:00Z",
                "browser_download_url":
                    f"/releases/download/{self.tag}/melo-{self.tag}-{abi}.apk",
            }
            for abi in ("arm64-v8a", "armeabi-v7a")
        ]
        return {
            "tag_name": self.tag,
            "name": f"Melo {self.tag.lstrip('v')}",
            "body": (
                "### What's new\n\n"
                "- Local test release served from the test script\n"
                "- Per-ABI APKs selected by the device\n"
                "- Cancel and retry keep the partial download\n"
            ),
            "html_url": "https://github.com/Fector101/Melo/releases",
            "published_at": "2026-10-26T00:00:00Z",
            "assets": assets,
        }

    # -- requests -------------------------------------------------------- #
    def asset_requests(self) -> list[dict]:
        return [item for item in self.requests
                if item["path"].startswith("/releases/download/")]

    def last_asset_name(self) -> str:
        assets = self.asset_requests()
        if not assets:
            raise TestFailure("the app never asked for an APK")
        return os.path.basename(assets[-1]["path"])

    def _record(self, path: str, request_range: str, status: int) -> None:
        self.requests.append(
            {"path": path, "range": request_range, "status": status,
             "at": time.time()})

    def _handler(self):
        payload = json.dumps(self.release()).encode()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # keep the test output clean
                pass

            def do_GET(self):  # noqa: N802 - http.server API
                path = self.path.split("?", 1)[0].rstrip("/")
                if path == "/releases/latest":
                    outer._record(path, "", 200)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path.startswith(f"/releases/download/{outer.tag}/"):
                    outer._serve_apk(self, path)
                    return
                outer._record(path, "", 404)
                self.send_error(404)

        return Handler

    def _serve_apk(self, handler: BaseHTTPRequestHandler, path: str) -> None:
        header = handler.headers.get("Range", "")
        match = self.RANGE.match(header)
        start = int(match.group(1)) if match else 0
        if start >= self.size:
            self._record(path, header, 416)
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{self.size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        status = 206 if match else 200
        self._record(path, header, status)
        handler.send_response(status)
        handler.send_header("Content-Type",
                            "application/vnd.android.package-archive")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(self.size - start))
        if match:
            handler.send_header(
                "Content-Range", f"bytes {start}-{self.size - 1}/{self.size}")
        handler.end_headers()
        try:
            with self.apk.open("rb") as handle:
                handle.seek(start)
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    if self.rate:
                        time.sleep(len(chunk) / self.rate)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the app cancelled; that is a case the test exercises


# --------------------------------------------------------------------------- #
# Reading the update screen                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    """What the update modal currently shows."""

    frame: Frame
    pill: Rect | None = None
    state: str = "unknown"          # available | downloading | ready | failed
    primary: tuple[int, int] | None = None
    secondary: tuple[int, int] | None = None
    ink_ratio: float = 0.0

    def describe(self) -> str:
        if self.pill is None:
            return "no button"
        centre = self.pill.center
        return (f"{self.state}, pill {self.pill.width}x{self.pill.height} "
                f"@ {centre}, ink {self.ink_ratio:.2f}")


def find_pill(frame: Frame) -> Rect | None:
    """The primary button: the widest accent band below the app bar."""
    top = int(frame.height * MIN_PILL_TOP)
    region = Rect(0, top, frame.width, int(frame.height * 0.75))
    for color in (ACCENT, ACCENT_DIM):
        band = frame.band(color, region, tol=10, step=2, min_run=100)
        if (band is not None and band.width >= MIN_PILL_WIDTH
                and band.height >= MIN_PILL_HEIGHT):
            return band
    return None


def secondary_center(frame: Frame, pill: Rect) -> tuple[int, int] | None:
    """The outlined pill to the right of the primary one ("Later"/"Cancel")."""
    region = Rect(pill.x1 + 4, pill.y0 - 6, frame.width, pill.y1 + 6)
    outline = frame.bbox(LINE, region, tol=8, step=1)
    if outline is not None and outline.width > 80:
        return outline.center
    # Fallback: 10 dp spacing + half of the 96 dp wide pill, at 2x density.
    return (pill.x1 + 116, pill.center_y)


def snapshot(frame: Frame) -> Snapshot:
    """Classify the modal from its pixels."""
    pill = find_pill(frame)
    if pill is None:
        return Snapshot(frame)
    probe = frame.pixel(pill.x0 + 8, pill.center_y)
    enabled = max(abs(probe[i] - ACCENT[i]) for i in range(3)) <= 14

    status_rect = Rect(pill.x0, max(0, pill.y0 - 160), pill.x1, pill.y0 - 4)
    green = frame.count(OK, status_rect, tol=10, step=2)
    red = frame.count(DANGER, status_rect, tol=10, step=2)
    if green > 40:
        state = "ready"
    elif red > 40:
        state = "failed"
    elif enabled:
        state = "available"
    else:
        state = "downloading"

    ink = frame.ink(pill)
    ratio = (ink.width / pill.width) if ink else 1.0
    return Snapshot(frame, pill, state, pill.center,
                    secondary_center(frame, pill), ratio)


def modal_visible(frame: Frame) -> bool:
    """The modal is a big card plus a wide pill, not just the app background."""
    pill = find_pill(frame)
    if pill is None:
        return False
    card = frame.count(CARD, tol=8, step=4,
                       rect=Rect(0, 200, frame.width, frame.height - 200))
    return card > 300


def dump_frame(frame: Frame, title: str = "frame") -> None:
    """Print the diagnostics an agent would want after a failed check."""
    print(f"\n--- {title} ---")
    print(f"{frame.width}x{frame.height} mean {hex_color(frame.mean())}")
    for color, hits in frame.dominant(limit=5):
        print(f"  {hex_color(color)}  {hits} samples")
    print(frame.ascii_map(cols=46, rows=26))


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #
def version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or ""))
    if not match:
        return (0,)
    return tuple(int(part or 0) for part in match.groups())


def find_apk(explicit: str | None) -> Path:
    """Locate the built debug APK: --apk, $MELO_APK, then the usual bin dirs."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise TestFailure(f"--apk does not exist: {path}")
        return path
    env = os.environ.get("MELO_APK")
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise TestFailure(f"$MELO_APK does not exist: {path}")
        return path
    roots = [Path.cwd(), Path(__file__).resolve().parent.parent,
             Path("/home/fabian/Documents/python-android")]
    found: list[Path] = []
    for root in roots:
        found.extend(sorted(root.glob("bin/melo-*-debug.apk")))
    if not found:
        raise TestFailure(
            "no APK found: pass --apk path/to/melo-*-debug.apk")
    return max(found, key=lambda item: item.stat().st_mtime)


def wait_for(callback, timeout: float, what: str, interval: float = 0.35):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            value = callback()
        except (AdbError, TestFailure) as error:
            last_error = error
            value = None
        if value:
            return value
        time.sleep(interval)
    detail = f" ({last_error})" if last_error else ""
    raise TestFailure(f"timed out after {timeout:.0f}s waiting for {what}{detail}")


def wait_snapshot(adb: Adb, wanted: str, timeout: float,
                  label: str | None = None) -> Snapshot:
    def read():
        current = snapshot(adb.screen())
        return current if current.state == wanted else None

    try:
        return wait_for(read, timeout, label or f"state {wanted}")
    except TestFailure:
        dump_frame(adb.screen(), "screen when waiting for " + (label or wanted))
        raise


def wait_modal(adb: Adb, timeout: float) -> Snapshot:
    def read():
        frame = adb.screen()
        return snapshot(frame) if modal_visible(frame) else None

    try:
        return wait_for(read, timeout, "the update modal")
    except TestFailure:
        dump_frame(adb.screen(), "screen when waiting for the modal")
        raise


def wait_gone(adb: Adb, timeout: float) -> Frame:
    def read():
        frame = adb.screen()
        return frame if find_pill(frame) is None else None

    return wait_for(read, timeout, "the modal to close")


def wait_log(adb: Adb, needle: str, timeout: float) -> str:
    def read():
        output = adb.logs()
        return needle if needle in output else None

    return wait_for(read, timeout, f"log {needle!r}")


def log_request_count(server: FakeRelease) -> int:
    return len(server.requests)


def restart_app(adb: Adb) -> None:
    """Force-stop, wait for the process to really die, then launch.

    Starting immediately after ``force-stop`` can leave the old window on
    screen for a moment, and a screenshot taken then would describe the state
    the app had *before* the restart.
    """
    adb.force_stop(PACKAGE)
    wait_for(lambda: adb.pidof(PACKAGE) is None, 15, "the app process to stop")
    adb.start(ACTIVITY)


# --------------------------------------------------------------------------- #
# The scenarios                                                               #
# --------------------------------------------------------------------------- #
def check_preflight(adb: Adb, report: Report, offered: str) -> str:
    report.step("preflight")
    state = adb.state()
    report.check("a device is connected", state == "device", f"adb get-state={state}")

    awake, why = adb.screen_on_and_unlocked()
    if not awake:
        adb.wake()
        time.sleep(1.0)
        awake, why = adb.screen_on_and_unlocked()
    if not awake:
        raise TestFailure(
            f"{why}. Unlock the phone, run `adb shell svc power stayon true` "
            "and keep the screen on; Kivy cannot create a surface while the "
            "display is off, and every screenshot would be black.")

    listing = adb.shell(f"dumpsys package {PACKAGE}")
    installed = re.search(r"versionName=(\S+)", listing)
    report.check("Melo is installed", installed is not None,
                 installed.group(1) if installed else "package not found")
    installed_version = installed.group(1) if installed else "0.0.0"
    report.check(
        f"installed {installed_version} is older than the offered {offered}",
        version_tuple(installed_version) < version_tuple(offered),
        "" if version_tuple(installed_version) < version_tuple(offered)
        else "install a build whose version is lower than --version")
    return installed_version


def check_endpoint(adb: Adb, server: FakeRelease, report: Report,
                   keep: bool) -> None:
    report.step("test plumbing")
    adb.reverse(server.port)
    report.check("adb reverse tunnel", True,
                 f"tcp:{server.port} -> host tcp:{server.port}")

    payload = json.dumps({
        "api_url": f"http://127.0.0.1:{server.port}/releases/latest",
        "base_url": f"http://127.0.0.1:{server.port}/releases/download",
    }).encode()
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as handle:
        handle.write(payload)
        local = handle.name
    try:
        adb.run("push", local, "/data/local/tmp/melo_update_endpoint.json")
    finally:
        os.unlink(local)
    adb.run_as(PACKAGE, "rm -f files/melo-*.apk", check=False)
    adb.run_as(PACKAGE,
               "cp /data/local/tmp/melo_update_endpoint.json "
               f"files/{ENDPOINT_FILE}")
    adb.run("shell", "rm -f /data/local/tmp/melo_update_endpoint.json",
            check=False)
    written = adb.run_as(PACKAGE, f"cat files/{ENDPOINT_FILE}", check=False)
    report.check("endpoint override written and old APKs cleared",
                 f'"api_url"' in written and str(server.port) in written,
                 f"127.0.0.1:{server.port}, "
                 f"cleanup={'off (--keep)' if keep else 'on'}")


def check_modal_opens(adb: Adb, report: Report, timeout: float) -> Snapshot:
    report.step("the modal renders (the black-screen regression)")
    adb.clear_logs()
    started = time.time()
    restart_app(adb)
    snap = wait_modal(adb, timeout)
    elapsed = time.time() - started
    frame = snap.frame
    report.check("the update modal is on screen", True,
                 f"after {elapsed:.1f}s, {snap.describe()}")
    report.check("it is not a black screen",
                 frame.mean()[0] > 8 and frame.count(CARD, step=4) > 300,
                 f"mean {hex_color(frame.mean())}, "
                 f"card {frame.count(CARD, step=4)} px")
    report.check("it opens in the available state", snap.state == "available",
                 snap.describe())
    return snap


def check_download_and_cancel(adb: Adb, server: FakeRelease, report: Report,
                              snap: Snapshot) -> tuple[int, str]:
    report.step("download, then cancel")
    report.check("primary button found", snap.primary is not None,
                 snap.describe())
    asset_before = len(server.asset_requests())
    assert snap.primary is not None
    adb.tap(*snap.primary)

    def started():
        current = len(server.asset_requests())
        return current if current > asset_before else None

    wait_for(started, 15, "the app to request the APK")
    request = server.asset_requests()[-1]
    report.check("the APK download started", request["status"] == 200,
                 f"{request['path']} -> {request['status']}")
    apk_name = os.path.basename(request["path"])
    path = f"files/{apk_name}"

    snap = wait_snapshot(adb, "downloading", 10)
    report.check("the button shows the downloading state", True, snap.describe())

    def partial():
        size = adb.file_size(PACKAGE, path)
        return size if size and 0 < size < server.size else None

    size = wait_for(partial, 30, "the partial APK to reach the phone")
    report.check("bytes are arriving", size > 0, f"{size:,} of {server.size:,}")

    assert snap.secondary is not None
    adb.tap(*snap.secondary)
    wait_log(adb, "[Download cancelled]", 10)
    snap = wait_snapshot(adb, "available", 10)
    report.check("cancel returns to the available state", True, snap.describe())
    kept = adb.file_size(PACKAGE, path)
    report.check("the partial file is kept for a resume", bool(kept),
                 f"{kept:,} bytes" if kept else "file gone")
    time.sleep(1.0)
    report.check("nothing keeps writing after cancel",
                 adb.file_size(PACKAGE, path) == kept,
                 f"{adb.file_size(PACKAGE, path)} vs {kept}")
    return kept or 0, apk_name


def check_resume_and_complete(adb: Adb, server: FakeRelease, report: Report,
                              partial: int, apk_name: str, rate: int,
                              scale: float) -> Snapshot:
    report.step("resume, then finish")
    path = f"files/{apk_name}"
    before = len(server.asset_requests())
    snap = snapshot(adb.screen())
    report.check("primary button is enabled again", snap.state == "available",
                 snap.describe())
    assert snap.primary is not None
    adb.tap(*snap.primary)

    def resumed():
        current = len(server.asset_requests())
        return current if current > before else None

    wait_for(resumed, 15, "the resumed request")
    request = server.asset_requests()[-1]
    report.check("the resume was sent as a Range request",
                 request["status"] == 206 and request["range"].startswith("bytes="),
                 f"{request['status']} {request['range']!r}")
    start = int(re.search(r"(\d+)", request["range"]).group(1))
    report.check("it resumes at the byte where Cancel stopped", start == partial,
                 f"Range starts at {start:,}, partial was {partial:,}")
    wait_log(adb, "Resuming download from byte", 10)

    budget = (server.size / rate if rate else 30) + 60
    def complete():
        size = adb.file_size(PACKAGE, path)
        return size if size == server.size else None

    size = wait_for(complete, max(60.0, budget * scale),
                    "the APK to finish downloading")
    report.check("the finished APK has the advertised size",
                 size == server.size, f"{size:,} bytes")

    snap = wait_snapshot(adb, "ready", 15)
    report.check("the screen switches to ready", True, snap.describe())
    report.check("the primary button now says Install",
                 snap.ink_ratio < SHORT_LABEL_RATIO,
                 f"ink ratio {snap.ink_ratio:.2f} < {SHORT_LABEL_RATIO}")
    return snap


def last_update_time(adb: Adb) -> str | None:
    listing = adb.shell(f"dumpsys package {PACKAGE}")
    match = re.search(r"lastUpdateTime=([0-9-]+ [0-9:]+)", listing)
    return match.group(1) if match else None


def install_start_line(adb: Adb) -> str | None:
    """The logcat START line for the installer intent, if it happened.

    This is the reliable signal: MIUI can put its own risk dialog over the app
    while ``topResumedActivity`` still reports Melo, so "which activity is on
    top" is not something to assert on.
    """
    for line in adb.run("logcat", "-d", "-t", "2000", check=False).splitlines():
        if ("dat=content://" in line and "package-archive" in line
                and "packageinstaller" in line):
            return line
    return None


def check_install(adb: Adb, report: Report, snap: Snapshot,
                  skip: bool, scale: float) -> None:
    report.step("install")
    assert snap.primary is not None
    adb.clear_logs()
    before = last_update_time(adb)
    adb.tap(*snap.primary)
    wait_log(adb, "[Called do_android_install]", 10)

    line = wait_for(lambda: install_start_line(adb), 15,
                    "the FileProvider install intent")
    report.check("the installer was handed the APK through the FileProvider",
                 True, line.split("dat=", 1)[1].split(" ", 1)[0][:60])
    report.info(f"top activity after Install: "
                f"{adb.top_activity().split(' ')[0][:70] or 'none'}")

    if skip:
        adb.key(4)
        adb.force_stop("com.google.android.packageinstaller")
        restart_app(adb)
        report.skip("the package is actually replaced", "--skip-install")
        return

    deadline = time.time() + 120 * scale
    hinted_at = 0.0
    while time.time() < deadline:
        now = last_update_time(adb)
        if now and before and now != before:
            report.check("the package was replaced by the downloaded APK", True,
                         f"lastUpdateTime {before} -> {now}")
            return
        if time.time() - hinted_at > 8:
            hinted_at = time.time()
            covered = find_pill(adb.screen()) is None
            if covered:
                hint = "a system dialog is over the app - approve it on the phone"
            else:
                hint = (f"top activity "
                        f"{adb.top_activity().split(' ')[0][:60] or 'none'}")
            report.info(f"waiting for the install: {hint}")
        time.sleep(2)
    raise TestFailure("the installer never replaced the package "
                      "(a MIUI/Play Protect prompt needs approving; rerun after)")


def check_cached_apk_and_chip(adb: Adb, server: FakeRelease, report: Report,
                              timeout: float) -> None:
    report.step("cached APK, chip and reopen (no extra network)")
    restart_app(adb)
    snap = wait_modal(adb, timeout)
    report.check("the modal opens again after the update", True, snap.describe())
    report.check("a fresh start does not auto-install the cached APK",
                 snap.state == "available", snap.describe())
    report.check("it still renders (fix survives the self-update)",
                 snap.frame.count(CARD, step=4) > 300,
                 f"card {snap.frame.count(CARD, step=4)} px")

    before = log_request_count(server)
    assert snap.primary is not None
    adb.tap(*snap.primary)
    snap = wait_snapshot(adb, "ready", 10)
    report.check("a complete cached APK jumps straight to Install",
                 snap.ink_ratio < SHORT_LABEL_RATIO,
                 f"ink ratio {snap.ink_ratio:.2f}")
    report.check("...without downloading anything again",
                 log_request_count(server) == before,
                 f"{log_request_count(server) - before} new request(s), "
                 f"{len(server.asset_requests())} APK request(s) total")

    before = log_request_count(server)
    assert snap.secondary is not None
    adb.tap(*snap.secondary)
    wait_gone(adb, 10)
    frame = adb.screen()
    chip = frame.band(ACCENT, Rect(0, 0, frame.width, int(frame.height * 0.2)),
                      tol=10, step=2, min_run=80)
    report.check("dismissing shows the update chip in the corner",
                 chip is not None and chip.width > 100,
                 f"chip {chip}" if chip else "no chip found")
    if chip is None:
        return
    adb.tap(*chip.center)
    snap = wait_modal(adb, 10)
    report.check("tapping the chip reopens the same screen", True, snap.describe())
    report.check("reopening does not run the update check again",
                 log_request_count(server) == before,
                 f"{log_request_count(server) - before} new request(s)")


def check_logs(adb: Adb, report: Report) -> None:
    report.step("logs")
    logs = adb.logs()
    tracebacks = [line for line in logs.splitlines() if "Traceback (most recent call last)" in line]
    report.check("no Python traceback in logcat", not tracebacks,
                 f"{len(tracebacks)} traceback(s)" if tracebacks else "clean")
    if tracebacks:
        tail = logs.split("Traceback (most recent call last)")[-1]
        print("\n".join(tail.splitlines()[:20]))


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    report = Report()
    adb = Adb(serial=args.serial, executable=args.adb)
    apk = find_apk(args.apk)
    server = FakeRelease(apk, args.version, port=args.port, rate=args.rate).start()
    print(f"Melo self-update device test\n"
          f"  adb     : {adb.executable}\n"
          f"  apk     : {apk} ({server.size:,} bytes)\n"
          f"  release : {server.tag} on 127.0.0.1:{server.port} "
          f"(rate {args.rate or 'unlimited'} B/s)")

    started_pid = None
    try:
        check_preflight(adb, report, args.version)
        check_endpoint(adb, server, report, keep=args.keep)
        snap = check_modal_opens(adb, report, 60 * args.timeout_scale)
        started_pid = adb.pidof(PACKAGE)

        partial, apk_name = check_download_and_cancel(adb, server, report, snap)
        if partial <= 0:
            report.skip("resume", "nothing was downloaded before Cancel")
        else:
            snap = check_resume_and_complete(
                adb, server, report, partial, apk_name, args.rate,
                args.timeout_scale)
            check_install(adb, report, snap, skip=args.skip_install,
                          scale=args.timeout_scale)
            check_cached_apk_and_chip(
                adb, server, report, 60 * args.timeout_scale)
        check_logs(adb, report)
    finally:
        adb.reverse_remove(server.port)
        if not args.keep:
            adb.run_as(PACKAGE, "rm -f files/melo-*.apk "
                                f"files/{ENDPOINT_FILE}", check=False)
            print("\ncleaned the device (endpoint override + downloaded APKs); "
                  "use --keep to leave them")
        server.stop()
        if started_pid:
            print(f"app pid was {started_pid}, now {adb.pidof(PACKAGE)}")
    return report.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end self-update test on a connected Android phone.")
    parser.add_argument("--apk", default=None,
                        help="APK to serve as the new release (default: newest "
                             "bin/melo-*-debug.apk)")
    parser.add_argument("--version", default="0.0.2",
                        help="version to advertise; must be newer than the app")
    parser.add_argument("--serial", default=None, help="adb serial")
    parser.add_argument("--adb", default=None, help="path to adb")
    parser.add_argument("--port", type=int, default=8000,
                        help="host port for the fake release (0 = random)")
    parser.add_argument("--rate", type=int, default=3_000_000,
                        help="download throttle in bytes/sec (0 = unlimited; "
                             "a throttle keeps Cancel and resume observable)")
    parser.add_argument("--skip-install", action="store_true",
                        help="stop after the installer intent; do not replace "
                             "the package")
    parser.add_argument("--keep", action="store_true",
                        help="leave the endpoint override and APK on the phone")
    parser.add_argument("--timeout-scale", type=float, default=1.0,
                        help="multiply the long timeouts (slow phone/build)")
    args = parser.parse_args(argv)

    try:
        return run(args)
    except TestFailure as error:
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
