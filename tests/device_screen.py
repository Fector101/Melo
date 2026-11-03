#!/usr/bin/env python3
"""Read a phone screen as pixels instead of pictures.

Why this exists
---------------
Kivy paints the whole UI into one SDL surface, so Android's accessibility tree
is empty for Melo: ``uiautomator dump`` shows nothing useful and there is no
resource id to tap. Everything has to go through the framebuffer, which means
"look at the screenshot" - and an agent cannot look at a screenshot. This
module turns a frame into numbers: colour histograms, bounding boxes, ink
widths and an ASCII map that is legible in a terminal (or in a log).

Grabbing a frame
----------------
``adb exec-out screencap`` (no ``-p``) returns a header followed by raw pixels:

    width (u32 LE)  height (u32 LE)  format (u32 LE)  [dataspace (u32 LE)]
    then width * height * 4 bytes

The header is 12 bytes on old Android and 16 on Android 9+; both are accepted
by comparing the payload size with the declared dimensions. Format 1 is
RGBA_8888, 4 is BGRA_8888. No Pillow needed on the device path (``--png``
uses it when it is installed).

Reading it
----------
Flat UI colours survive the round trip exactly (Kivy paints ``[.11, .12, .15]``
as ``rgb(28, 31, 38)``), so matching with a small tolerance is reliable:
``Frame.count`` / ``Frame.bbox`` / ``Frame.band``. ``Frame.ascii_map`` improves
on a naive ramp by boosting the brightness (``gain``) so that a dark theme
still shows structure instead of a wall of spaces.

Command line
------------
    python3 tests/device_screen.py                  # grab and describe
    python3 tests/device_screen.py --find '#5cb8f0' # locate a colour
    python3 tests/device_screen.py --png shot.png   # offline frame
    python3 tests/device_screen.py --json           # machine readable

Run it with the project venv (``venv/bin/python``) on the desktop.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple, Sequence

#: Terminal ramp, dark to bright. With ``gain=3`` a 10% grey lands on ':'.
RAMP = " .:-=+*#%@"

#: Where buildozer keeps the SDK adb on this machine.
DEFAULT_ADB = "~/.buildozer/android/platform/android-sdk/platform-tools/adb"

FORMAT_NAMES = {1: "RGBA_8888", 2: "RGBX_8888", 3: "RGB_565", 4: "BGRA_8888"}


class AdbError(RuntimeError):
    """An adb command failed (or adb is not where we expect it)."""


def find_adb() -> str:
    """Locate the adb binary: $ADB, $PATH, then the buildozer SDK."""
    override = os.environ.get("ADB")
    if override:
        return override
    found = shutil.which("adb")
    if found:
        return found
    candidate = Path(DEFAULT_ADB).expanduser()
    if candidate.exists():
        return str(candidate)
    raise AdbError(
        "adb not found: set $ADB, put adb on $PATH, or install the Android SDK")


def parse_color(text: str) -> tuple[int, int, int]:
    """``'#5cb8f0'``, ``'5cb8f0'``, ``'92,184,240'`` -> ``(92, 184, 240)``."""
    text = str(text).strip()
    if "," in text:
        parts = [int(part) for part in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"expected 3 channels, got {text!r}")
        return tuple(parts)  # type: ignore[return-value]
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #rrggbb, got {text!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def parse_rect(text: str) -> tuple[int, int, int, int]:
    """``'x0,y0,x1,y1'`` -> a 4-tuple of ints."""
    parts = [int(part) for part in str(text).split(",")]
    if len(parts) != 4:
        raise ValueError(f"expected x0,y0,x1,y1, got {text!r}")
    return tuple(parts)  # type: ignore[return-value]


def hex_color(rgb: Sequence[int]) -> str:
    return "#%02x%02x%02x" % tuple(rgb[:3])


def luma(rgb: Sequence[int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


class Rect(NamedTuple):
    """A half-open pixel rectangle in screen coordinates."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[int, int]:
        return (self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2

    @property
    def center_x(self) -> int:
        return (self.x0 + self.x1) // 2

    @property
    def center_y(self) -> int:
        return (self.y0 + self.y1) // 2

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def expand(self, by: int) -> "Rect":
        return Rect(self.x0 - by, self.y0 - by, self.x1 + by, self.y1 + by)

    def as_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass
class Frame:
    """One screenshot, addressable by pixel."""

    width: int
    height: int
    data: bytes
    offset: int = 0
    fmt: str = "RGBA_8888"

    # -- construction ---------------------------------------------------- #
    @classmethod
    def from_raw(cls, blob: bytes) -> "Frame":
        if len(blob) < 12:
            raise ValueError(f"screencap returned {len(blob)} bytes, no header")
        width, height, code = struct.unpack_from("<III", blob, 0)
        pixels = width * height * 4
        if len(blob) - 12 == pixels:
            offset = 12
        elif len(blob) - 16 == pixels:
            offset = 16
        else:
            raise ValueError(
                f"unexpected screencap payload: {width}x{height} needs "
                f"{pixels} bytes, got {len(blob) - 12} after the header")
        fmt = FORMAT_NAMES.get(code)
        if fmt not in ("RGBA_8888", "RGBX_8888", "BGRA_8888"):
            raise ValueError(f"unsupported screencap format {code} ({fmt})")
        return cls(width, height, blob, offset, fmt)

    @classmethod
    def from_png(cls, path: str | Path) -> "Frame":
        try:
            from PIL import Image
        except ImportError as error:  # pragma: no cover - desktop convenience
            raise RuntimeError("--png needs Pillow in the current venv") from error

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            return cls(rgba.width, rgba.height, rgba.tobytes(), 0, "RGBA_8888")

    # -- pixels ---------------------------------------------------------- #
    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """The RGB triple at ``(x, y)``."""
        index = self.offset + (y * self.width + x) * 4
        data = self.data
        red, green, blue = data[index], data[index + 1], data[index + 2]
        if self.fmt == "BGRA_8888":
            red, blue = blue, red
        return red, green, blue

    def _clamp(self, rect: Rect | None) -> Rect:
        if rect is None:
            return Rect(0, 0, self.width, self.height)
        return Rect(
            max(0, rect[0]), max(0, rect[1]),
            min(self.width, rect[2]), min(self.height, rect[3]),
        )

    def _walk(self, rect: Rect | None = None,
              step: int = 2) -> Iterator[tuple[int, int, int, int, int]]:
        """Yield ``(x, y, r, g, b)`` on a grid inside ``rect``."""
        box = self._clamp(rect)
        step = max(1, int(step))
        data = self.data
        width = self.width
        offset = self.offset
        bgra = self.fmt == "BGRA_8888"
        for y in range(box.y0, box.y1, step):
            row = offset + y * width * 4
            for x in range(box.x0, box.x1, step):
                index = row + x * 4
                red, green, blue = data[index], data[index + 1], data[index + 2]
                if bgra:
                    red, blue = blue, red
                yield x, y, red, green, blue

    # -- measurements ---------------------------------------------------- #
    def mean(self, rect: Rect | None = None, step: int = 4) -> tuple[int, int, int]:
        """Average RGB of a region."""
        total = [0, 0, 0]
        count = 0
        for _x, _y, red, green, blue in self._walk(rect, step):
            total[0] += red
            total[1] += green
            total[2] += blue
            count += 1
        if not count:
            return (0, 0, 0)
        return tuple(round(value / count) for value in total)  # type: ignore[return-value]

    def count(self, color: Sequence[int], rect: Rect | None = None,
              tol: int = 8, step: int = 2) -> int:
        """How many sampled pixels are within ``tol`` of ``color``."""
        red0, green0, blue0 = color[0], color[1], color[2]
        hits = 0
        for _x, _y, red, green, blue in self._walk(rect, step):
            if (abs(red - red0) <= tol and abs(green - green0) <= tol
                    and abs(blue - blue0) <= tol):
                hits += 1
        return hits

    def bbox(self, color: Sequence[int], rect: Rect | None = None,
             tol: int = 8, step: int = 2) -> Rect | None:
        """Bounding box of every sampled pixel within ``tol`` of ``color``."""
        red0, green0, blue0 = color[0], color[1], color[2]
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for x, y, red, green, blue in self._walk(rect, step):
            if (abs(red - red0) <= tol and abs(green - green0) <= tol
                    and abs(blue - blue0) <= tol):
                x0 = min(x0, x)
                y0 = min(y0, y)
                x1 = max(x1, x)
                y1 = max(y1, y)
        if x1 < 0:
            return None
        return Rect(x0, y0, x1 + 1, y1 + 1)

    def band(self, color: Sequence[int], rect: Rect | None = None,
             tol: int = 8, step: int = 1, min_run: int = 120) -> Rect | None:
        """The widest horizontal band of ``color``.

        A UI pill is a wide, short run of one colour: many matching pixels in
        consecutive rows. This finds the longest such run and returns the box
        around it, which works for buttons of any size (no coordinates in the
        test), and ignores thin text because a row of text never reaches
        ``min_run`` matching pixels.
        """
        box = self._clamp(rect)
        red0, green0, blue0 = color[0], color[1], color[2]
        rows: list[tuple[int, int, int, int]] = []  # y, hits, first_x, last_x
        for y in range(box.y0, box.y1, max(1, step)):
            hits = 0
            first = last = -1
            for x, _y, red, green, blue in self._walk(Rect(box.x0, y, box.x1, y + 1), step):
                if (abs(red - red0) <= tol and abs(green - green0) <= tol
                        and abs(blue - blue0) <= tol):
                    hits += 1
                    if first < 0:
                        first = x
                    last = x
            rows.append((y, hits, first, last))

        best = None
        run: list[tuple[int, int, int, int]] = []

        def flush() -> None:
            nonlocal best, run
            if run and (best is None or len(run) > len(best)):
                best = list(run)
            run = []

        for row in rows:
            if row[1] >= min_run:
                run.append(row)
            else:
                flush()
        flush()
        if not best:
            return None
        return Rect(
            min(row[2] for row in best),
            min(row[0] for row in best),
            max(row[3] for row in best) + 1,
            max(row[0] for row in best) + 1,
        )

    def dominant(self, rect: Rect | None = None, step: int = 3,
                 limit: int = 6) -> list[tuple[tuple[int, int, int], int]]:
        """The most common exact colours in a region."""
        histogram: Counter = Counter()
        for _x, _y, red, green, blue in self._walk(rect, step):
            histogram[(red, green, blue)] += 1
        return histogram.most_common(limit)

    def bright_bbox(self, threshold: int = 30,
                    rect: Rect | None = None, step: int = 3) -> Rect | None:
        """Bounding box of everything brighter than ``threshold``."""
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for x, y, red, green, blue in self._walk(rect, step):
            if max(red, green, blue) > threshold:
                x0 = min(x0, x)
                y0 = min(y0, y)
                x1 = max(x1, x)
                y1 = max(y1, y)
        if x1 < 0:
            return None
        return Rect(x0, y0, x1 + 1, y1 + 1)

    def ink(self, rect: Rect, threshold: int = 120,
            inset_x: int | None = None, inset_y: int | None = None) -> Rect | None:
        """Bounding box of dark glyphs inside a filled control.

        Measuring the glyph run instead of the painted pill avoids the
        anti-aliased edge, which is dark all the way across. A short label
        ("Install") and a long one ("Download update") then differ by a factor
        of three in ``width``.
        """
        box = self._clamp(rect)
        pad_x = inset_x if inset_x is not None else max(2, box.width // 12)
        pad_y = inset_y if inset_y is not None else max(2, box.height // 5)
        inner = Rect(box.x0 + pad_x, box.y0 + pad_y,
                     box.x1 - pad_x, box.y1 - pad_y)
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for x, y, red, green, blue in self._walk(inner, 1):
            if luma((red, green, blue)) < threshold:
                x0 = min(x0, x)
                y0 = min(y0, y)
                x1 = max(x1, x)
                y1 = max(y1, y)
        if x1 < 0:
            return None
        return Rect(x0, y0, x1 + 1, y1 + 1)

    def ascii_map(self, rect: Rect | None = None, cols: int = 54,
                  rows: int | None = None, gain: float = 3.0) -> str:
        """A dark-theme-friendly ASCII rendering of the frame."""
        box = self._clamp(rect)
        cols = max(8, int(cols))
        if rows is None:
            rows = max(8, round(cols * box.height / max(1, box.width) / 2))
        rows = max(4, int(rows))
        cell_w = max(1, box.width / cols)
        cell_h = max(1, box.height / rows)
        step = max(1, int(min(cell_w, cell_h) // 6))
        lines = []
        for row in range(rows):
            y0 = box.y0 + int(row * cell_h)
            y1 = box.y0 + int((row + 1) * cell_h)
            line = []
            for col in range(cols):
                x0 = box.x0 + int(col * cell_w)
                x1 = box.x0 + int((col + 1) * cell_w)
                value = luma(self.mean(Rect(x0, y0, x1, y1), step=step))
                index = int(value / 255.0 * (len(RAMP) - 1) * gain)
                line.append(RAMP[min(len(RAMP) - 1, max(0, index))])
            lines.append("".join(line))
        return "\n".join(lines)

    def describe(self, rect: Rect | None = None) -> dict:
        """A JSON-friendly summary of the frame (or one region)."""
        box = self._clamp(rect)
        mean = self.mean(box)
        bright = self.bright_bbox(30, box)
        return {
            "width": self.width,
            "height": self.height,
            "format": self.fmt,
            "region": box.as_dict(),
            "mean": list(mean),
            "mean_hex": hex_color(mean),
            "bright_bbox": bright.as_dict() if bright else None,
            "dominant": [
                {"hex": hex_color(color), "rgb": list(color), "samples": hits}
                for color, hits in self.dominant(box)
            ],
        }


@dataclass
class Adb:
    """A thin, typed wrapper around the adb commands this project needs."""

    serial: str | None = None
    executable: str | None = None
    timeout: float = 90.0

    def __post_init__(self) -> None:
        self.executable = self.executable or find_adb()
        self.serial = (self.serial or os.environ.get("ANDROID_SERIAL") or None)

    # -- plumbing -------------------------------------------------------- #
    def _args(self, args: Iterable[str]) -> list[str]:
        base = [str(self.executable)]
        if self.serial:
            base += ["-s", self.serial]
        return base + [str(arg) for arg in args]

    def run(self, *args: str, binary: bool = False, check: bool = True,
            timeout: float | None = None, stdin: bytes | None = None):
        try:
            proc = subprocess.run(
                self._args(args), input=stdin, capture_output=True,
                timeout=timeout or self.timeout,
            )
        except FileNotFoundError as error:
            raise AdbError(f"cannot run {self.executable}: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise AdbError(f"adb {' '.join(args)} timed out") from error
        if check and proc.returncode != 0:
            message = (proc.stderr or proc.stdout).decode("utf-8", "replace")
            raise AdbError(f"adb {' '.join(args)} failed: {message.strip()}")
        if binary:
            return proc.stdout
        return proc.stdout.decode("utf-8", "replace")

    def shell(self, command: str, **kwargs):
        return self.run("shell", command, **kwargs)

    # -- device state ---------------------------------------------------- #
    def state(self) -> str:
        return self.run("get-state").strip()

    def wake(self) -> None:
        self.shell("input keyevent KEYCODE_WAKEUP")
        self.shell("wm dismiss-keyguard")

    def screen_on_and_unlocked(self) -> tuple[bool, str]:
        power = self.shell("dumpsys power")
        window = self.shell("dumpsys window")
        awake = "mWakefulness=Awake" in power
        keyguard = "mDreamingLockscreen=true" in window
        if not awake:
            return False, "screen is asleep"
        if keyguard:
            return False, "keyguard is showing (unlock the phone)"
        return True, "awake and unlocked"

    def top_activity(self) -> str:
        """The resumed activity component, e.g. ``pkg/org.kivy...``."""
        try:
            output = self.shell(
                "dumpsys activity activities | grep topResumedActivity")
        except AdbError:
            output = ""
        for line in output.splitlines():
            marker = "topResumedActivity="
            if marker in line:
                return line.split(marker, 1)[1].strip()
        return ""

    def pidof(self, package: str) -> int | None:
        try:
            output = self.shell(f"pidof {package}")
        except AdbError:
            return None
        for token in output.split():
            if token.isdigit():
                return int(token)
        return None

    def start(self, component: str) -> None:
        self.shell(f"am start -n {component}")

    def force_stop(self, package: str) -> None:
        self.shell(f"am force-stop {package}")

    # -- app private storage --------------------------------------------- #
    def run_as(self, package: str, command: str, check: bool = True) -> str:
        """Run a shell command as the app (``run-as``), e.g. to read files."""
        import shlex
        return self.shell(
            f"run-as {package} sh -c {shlex.quote(command)}", check=check)

    def file_size(self, package: str, path: str) -> int | None:
        output = self.run_as(package, f"wc -c < {path}", check=False)
        output = output.strip()
        return int(output) if output.isdigit() else None

    # -- screen ---------------------------------------------------------- #
    def screen(self) -> Frame:
        return Frame.from_raw(self.run("exec-out", "screencap", binary=True,
                                       timeout=30))

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x0: int, y0: int, x1: int, y1: int, ms: int = 200) -> None:
        self.shell(f"input swipe {int(x0)} {int(y0)} {int(x1)} {int(y1)} {int(ms)}")

    def key(self, code: int | str) -> None:
        self.shell(f"input keyevent {code}")

    # -- logs ------------------------------------------------------------ #
    def clear_logs(self) -> None:
        self.shell("logcat -c")

    def logs(self, tags: Sequence[str] = ("python",), lines: int = 1500) -> str:
        selector = ",".join(f"{tag}:V" for tag in tags)
        return self.run("logcat", "-d", "-t", str(lines), "-s", selector,
                        check=False)

    # -- port forwarding ------------------------------------------------- #
    def reverse(self, port: int) -> None:
        self.run("reverse", f"tcp:{port}", f"tcp:{port}")

    def reverse_remove(self, port: int) -> None:
        self.run("reverse", "--remove", f"tcp:{port}", check=False)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_map(frame: Frame, region: Rect | None, cols: int, rows: int | None,
               gain: float) -> None:
    print(frame.ascii_map(region, cols=cols, rows=rows, gain=gain))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Describe the phone screen in text: colours, boxes, ASCII.")
    parser.add_argument("--serial", default=None, help="adb serial")
    parser.add_argument("--adb", default=None, help="path to adb")
    parser.add_argument("--png", default=None,
                        help="analyse a PNG on disk instead of grabbing one")
    parser.add_argument("--find", default=None,
                        help="colour to locate, e.g. '#5cb8f0'")
    parser.add_argument("--tol", type=int, default=8, help="colour tolerance")
    parser.add_argument("--region", default=None, help="x0,y0,x1,y1")
    parser.add_argument("--band", type=int, default=0,
                        help="also find the widest band of --find this many px wide")
    parser.add_argument("--cols", type=int, default=54, help="map columns")
    parser.add_argument("--rows", type=int, default=None, help="map rows")
    parser.add_argument("--gain", type=float, default=3.0, help="map brightness gain")
    parser.add_argument("--no-map", action="store_true", help="skip the ASCII map")
    parser.add_argument("--json", action="store_true", help="machine readable")
    args = parser.parse_args(argv)

    region = parse_rect(args.region) if args.region else None
    try:
        if args.png:
            frame = Frame.from_png(args.png)
        else:
            frame = Adb(serial=args.serial, executable=args.adb).screen()
    except (AdbError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    report = frame.describe(region)
    if args.find:
        color = parse_color(args.find)
        box = frame.bbox(color, region, tol=args.tol, step=1)
        found = {
            "color": hex_color(color),
            "count": frame.count(color, region, tol=args.tol, step=1),
            "bbox": box.as_dict() if box else None,
            "center": list(box.center) if box else None,
        }
        if args.band:
            band = frame.band(color, region, tol=args.tol, min_run=args.band)
            found["band"] = band.as_dict() if band else None
            found["band_center"] = list(band.center) if band else None
        report["find"] = found

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"frame {frame.width}x{frame.height} {frame.fmt}")
        print(f"mean {hex_color(report['mean'])} rgb{tuple(report['mean'])}")
        bright = report["bright_bbox"]
        print(f"bright>30 bbox: {bright}")
        print("dominant:")
        samples = sum(item["samples"] for item in report["dominant"]) or 1
        for item in report["dominant"]:
            share = 100.0 * item["samples"] / samples
            print(f"  {item['hex']}  {share:5.1f}%  rgb{tuple(item['rgb'])}")
        if args.find:
            found = report["find"]
            print(f"find {found['color']}: {found['count']} px, "
                  f"bbox {found['bbox']}, center {found['center']}")
            if "band" in found:
                print(f"  band {found['band']} center {found['band_center']}")
        if not args.no_map:
            print(f"map {args.cols}x{args.rows or 'auto'} (gain {args.gain}):")
            _print_map(frame, region, args.cols, args.rows, args.gain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
