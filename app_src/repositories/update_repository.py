"""The GitHub release updater.

This module is imported lazily: nothing here may run at startup unless an
update is actually being checked for or shown. It keeps the download/resume
logic of the old Waller updater, but selects the APK that matches the device
ABI and reads the notes from the repository's version-notes file.

The network calls live here, never in a view model or a widget.
"""

import json
import logging
import os
import re
import tempfile

import requests

from android_notify.config import on_android_platform
from core.android_bridge import autoclass
from models.release import DEFAULT_HIGHLIGHTS, Release, ReleaseAsset

logger = logging.getLogger("melo.update")

DEFAULT_RELEASE_API_URL = (
    "https://api.github.com/repos/Fector101/Melo/releases/latest"
)
DEFAULT_RELEASE_BASE_URL = (
    "https://github.com/Fector101/Melo/releases/download"
)
RAW_RELEASE_NOTE_URL = (
    "https://raw.githubusercontent.com/Fector101/Melo/{tag}/"
    ".github/version-notes/release-note-v{version}.txt"
)
CONTRIBUTORS_API_URL = (
    "https://api.github.com/repos/Fector101/Melo/contributors?per_page=100"
)
OWNER = "Fector101"
UPDATE_ENDPOINT_FILENAME = "update_endpoint.json"
DOWNLOAD_TIMEOUT = (10, 30)
KNOWN_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
DEFAULT_RELEASE_NOTE = "\n".join("- " + line for line in DEFAULT_HIGHLIGHTS)
CONTRIBUTORS_LIMIT = 8

_contributors_cache = None


class RestartDownload(Exception):
    """A resume attempt cannot be trusted and has to start over from byte 0."""


class DownloadCancelled(Exception):
    """The user cancelled a download; the partial file is kept for a resume."""


# --------------------------------------------------------------------------- #
# Paths and endpoint overrides                                                #
# --------------------------------------------------------------------------- #
def get_apk_directory():
    """The directory that holds downloaded update APKs."""
    if on_android_platform():
        from android import mActivity  # type: ignore

        context = mActivity.getApplicationContext()
        return context.getFilesDir().getAbsolutePath()

    try:
        from kivy.app import App

        app = App.get_running_app()
        if app is not None and app.user_data_dir:
            return app.user_data_dir
    except Exception:
        pass
    return tempfile.gettempdir()


def get_apk_path(filename, directory=None):
    """The local path of an update APK (the file name is made safe)."""
    return os.path.join(directory or get_apk_directory(),
                        os.path.basename(str(filename)))


def get_update_endpoint_config():
    """Read ``<filesDir>/update_endpoint.json`` for local update testing.

    A debug build can be re-pointed at a laptop server by pushing the file
    into the app's files dir, with no rebuild.
    """
    path = os.path.join(get_apk_directory(), UPDATE_ENDPOINT_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        logger.exception("Ignoring unreadable update endpoint config: %s", path)
        return {}
    if not isinstance(config, dict):
        logger.warning("Ignoring non-object update endpoint config: %s", path)
        return {}
    return config


def get_release_api_url():
    return (os.environ.get("MELO_UPDATE_API_URL")
            or get_update_endpoint_config().get("api_url")
            or DEFAULT_RELEASE_API_URL)


def get_release_base_url():
    return (os.environ.get("MELO_UPDATE_BASE_URL")
            or get_update_endpoint_config().get("base_url")
            or DEFAULT_RELEASE_BASE_URL)


def has_update_api_override():
    """True when the check would reach something other than GitHub's default.

    Deliberately about ``api_url`` alone: a config that only sets ``base_url``
    leaves the version check on api.github.com, so counting it as an override
    would put a desktop/debug build back on the network.
    """
    return bool(os.environ.get("MELO_UPDATE_API_URL")
                or get_update_endpoint_config().get("api_url"))


# --------------------------------------------------------------------------- #
# Versions and device information                                             #
# --------------------------------------------------------------------------- #
_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _version_tuple(value):
    match = _VERSION.search(str(value or ""))
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(latest, installed):
    """True when ``latest`` is genuinely newer than ``installed``.

    If either side cannot be parsed, fall back to a plain inequality so a
    release with an unusual tag can still be offered once.
    """
    latest_tuple = _version_tuple(latest)
    installed_tuple = _version_tuple(installed)
    if latest_tuple is None or installed_tuple is None:
        return str(latest) != str(installed)
    return latest_tuple > installed_tuple


def get_installed_version():
    """The version Android installed, or the Python version off Android."""
    if on_android_platform():
        try:
            from android import mActivity  # type: ignore

            context = mActivity.getApplicationContext()
            info = context.getPackageManager().getPackageInfo(
                context.getPackageName(), 0)
            installed = str(info.versionName or "").strip()
            if installed:
                return installed
        except Exception as error_getting_version_name_from_android:
            logger.exception("Could not read the installed version: %s", error_getting_version_name_from_android)
    return "APP_VERSION"


def get_supported_abis():
    """The device's ABIs, in preference order, or ``()`` off Android."""
    if not on_android_platform() or autoclass is None:
        return ()
    try:
        build = autoclass("android.os.Build")
        abis = getattr(build, "SUPPORTED_ABIS", None)
        if abis is not None:
            return tuple(str(abi) for abi in abis)
        return tuple(
            str(getattr(build, name))
            for name in ("CPU_ABI", "CPU_ABI2")
            if getattr(build, name, None)
        )
    except Exception:
        logger.exception("Could not read the device ABIs")
        return ()


def asset_abi(name):
    """The ABI encoded in an APK asset name, or ``None`` when unknown."""
    name = str(name or "")
    for abi in KNOWN_ABIS:
        if name.endswith(f"-{abi}.apk"):
            return abi
    if name.endswith("-universal.apk"):
        return "universal"
    return None


def select_asset(assets, supported_abis):
    """Pick the best APK: device ABI order first, then a universal build."""
    by_abi = {
        asset.abi: asset
        for asset in assets
        if asset.abi and asset.abi != "universal"
    }
    for abi in supported_abis or ():
        asset = by_abi.get(str(abi))
        if asset is not None:
            return asset
    for asset in assets:
        if asset.abi == "universal":
            return asset
    return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_assets(data):
    """Turn GitHub's asset list into the APK choices Melo understands."""
    tag = str(data.get("tag_name") or "")
    base = get_release_base_url().rstrip("/")
    assets = []
    for raw in data.get("assets") or []:
        name = str(raw.get("name") or "")
        if not name.endswith(".apk"):
            continue
        browser_url = str(raw.get("browser_download_url") or "")
        if tag:
            download_url = f"{base}/{tag}/{name}"
        else:
            download_url = browser_url
        assets.append(ReleaseAsset(
            name=name,
            size=_as_int(raw.get("size")),
            download_url=download_url,
            abi=asset_abi(name),
            downloads=_as_int(raw.get("download_count")),
            updated_at=str(raw.get("updated_at") or ""),
        ))
    return assets


def get_release_note_txt(data, latest_version):
    """Read the version note from the tag, then fall back to the release body."""
    tag = str(data.get("tag_name") or f"v{latest_version}")
    url = RAW_RELEASE_NOTE_URL.format(tag=tag, version=latest_version)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        text = (response.text or "").strip()
        if text:
            return text
    except Exception:
        logger.info("No raw release note at %s", url)
    return str(data.get("body") or "").strip() or DEFAULT_RELEASE_NOTE


# --------------------------------------------------------------------------- #
# Release check                                                               #
# --------------------------------------------------------------------------- #
def check_for_update(installed_version=None, supported_abis=None):
    """Return a newer :class:`Release` for this device, or ``None``.

    No UI is touched here; the caller decides when (and whether) to show the
    update screen. Any network/parse failure simply means "no update".
    """
    installed = installed_version or get_installed_version()
    try:
        response = requests.get(get_release_api_url(), timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.exception("Update check failed")
        return None

    tag = str(data.get("tag_name") or "").strip()
    latest = tag[1:] if tag.startswith("v") else tag
    if not latest:
        logger.warning("The release payload has no tag_name")
        return None

    if not is_newer(latest, installed):
        try:
            find_and_delete_unused_apks(latest)
        except Exception:
            logger.exception("Could not remove unused update APKs")
        return None

    abis = supported_abis if supported_abis is not None else get_supported_abis()
    selected = select_asset(_parse_assets(data), abis)
    if selected is None:
        logger.warning("Release %s has no APK for device ABIs %s",
                       latest, abis)
        return None

    return Release(
        version=latest,
        tag=tag or f"v{latest}",
        notes=get_release_note_txt(data, latest),
        body=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or ""),
        published_at=str(data.get("published_at") or ""),
        asset=selected,
    )


# --------------------------------------------------------------------------- #
# Download                                                                    #
# --------------------------------------------------------------------------- #
def _resume_offset(headers):
    """The offset a 206 response claims to start at, or ``None`` if unusable.

    A 206 has to carry Content-Range, and its start has to match the offset we
    asked for; otherwise a server can replay the file from byte 0 and the
    append would silently duplicate a block.
    """
    unit, separator, range_spec = headers.get("Content-Range", "").partition(" ")
    start, dash, _end = range_spec.partition("-")
    if not separator or not dash or unit.lower() != "bytes":
        return None
    if not start.isascii() or not start.isdigit():
        return None
    return int(start)


def _download_apk_once(url, apk_path, existing_size,
                       progress_callback=None, cancel_event=None):
    headers = {}
    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"

    # The context manager returns the connection once the body is read or the
    # response is abandoned for a RestartDownload retry.
    with requests.get(url, headers=headers, stream=True,
                      timeout=DOWNLOAD_TIMEOUT) as response:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled()
        if response.status_code == 416 and existing_size > 0:
            raise RestartDownload()
        response.raise_for_status()
        if existing_size > 0 and response.status_code != 206:
            raise RestartDownload()
        if existing_size > 0:
            claimed_offset = _resume_offset(response.headers)
            if claimed_offset != existing_size:
                logger.warning(
                    "Server resumed at byte %s, expected %s (Content-Range: %r)",
                    claimed_offset, existing_size,
                    response.headers.get("Content-Range"))
                raise RestartDownload()

        total_size = _as_int(response.headers.get("content-length")) + existing_size
        downloaded = existing_size
        sent_percent = 0
        mode = "ab" if existing_size > 0 else "wb"

        with open(apk_path, mode) as target:
            for chunk in response.iter_content(8192):
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled()
                if not chunk:
                    continue
                target.write(chunk)
                downloaded += len(chunk)

                if total_size and progress_callback:
                    percent = int((downloaded / total_size) * 100)
                    if percent != sent_percent:
                        sent_percent = percent
                        progress_callback(percent)

    logger.info("Download completed: %s", apk_path)
    return apk_path


def download_apk(url, filename="melo-update.apk", progress_callback=None,
                 cancel_event=None, directory=None):
    """Download an APK with resume support.

    The partially downloaded file is intentionally kept on cancel or network
    failure, so the next attempt resumes it. ``DownloadCancelled`` is re-raised
    for the view model; every other failure returns ``None``.
    """
    try:
        folder = directory or get_apk_directory()
        os.makedirs(folder, exist_ok=True)
        apk_path = get_apk_path(filename, folder)
        existing_size = (os.path.getsize(apk_path)
                         if os.path.exists(apk_path) else 0)
        if existing_size:
            logger.info("Resuming download from byte %s", existing_size)
        try:
            return _download_apk_once(url, apk_path, existing_size,
                                      progress_callback, cancel_event)
        except RestartDownload:
            logger.warning("Resume unusable for %s, restarting from byte 0", url)
            return _download_apk_once(url, apk_path, 0,
                                      progress_callback, cancel_event)
    except DownloadCancelled:
        logger.info("Download cancelled: %s", filename)
        raise
    except Exception:
        logger.exception("Download failed: %s", filename)
        return None


# --------------------------------------------------------------------------- #
# Install                                                                     #
# --------------------------------------------------------------------------- #
def install_apk15(apk_path):
    """Install through a FileProvider (Android 15+)."""
    if not apk_path or not os.path.exists(apk_path):
        logger.info("APK not found: %s", apk_path)
        return False
    from jnius import autoclass as jnius_autoclass
    from android import mActivity  # type: ignore

    context = mActivity.getApplicationContext()
    Intent = jnius_autoclass("android.content.Intent")
    File = jnius_autoclass("java.io.File")
    FileProvider = jnius_autoclass("androidx.core.content.FileProvider")

    apk_file = File(apk_path)
    authority = context.getPackageName() + ".fileprovider"
    uri = FileProvider.getUriForFile(context, authority, apk_file)

    intent = Intent(Intent.ACTION_VIEW)
    intent.setDataAndType(uri, "application/vnd.android.package-archive")
    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    mActivity.startActivity(intent)
    return True


def install_apk(apk_path):
    """The legacy file:// installer for older Android versions."""
    if not apk_path or not os.path.exists(apk_path):
        logger.info("APK not found: %s", apk_path)
        return False
    from jnius import autoclass as jnius_autoclass
    from android import mActivity  # type: ignore

    Intent = jnius_autoclass("android.content.Intent")
    Uri = jnius_autoclass("android.net.Uri")
    File = jnius_autoclass("java.io.File")

    intent = Intent(Intent.ACTION_VIEW)
    apk_file = File(apk_path)
    uri = Uri.fromFile(apk_file)
    intent.setDataAndType(uri, "application/vnd.android.package-archive")
    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    mActivity.startActivity(intent)
    return True


def do_android_install(apk_path):
    """Start the system installer; return whether an intent was started."""
    logger.info("Called do_android_install: %s", apk_path)
    if not on_android_platform() or not apk_path or not os.path.exists(apk_path):
        return False
    try:
        if install_apk15(apk_path):
            return True
    except Exception:
        logger.exception("FileProvider install failed")
    try:
        return bool(install_apk(apk_path))
    except Exception:
        logger.exception("Legacy install failed")
        return False


# --------------------------------------------------------------------------- #
# Local files and contributors                                                #
# --------------------------------------------------------------------------- #
def apk_is_valid(path, expected_size):
    """Return ``path`` when the file exists with the expected size."""
    if not path or not os.path.exists(path):
        return None
    try:
        if os.path.getsize(path) == int(expected_size):
            return path
    except (OSError, TypeError, ValueError):
        return None
    return None


def find_and_delete_unused_apks(latest_version=None, directory=None):
    """Delete every downloaded update APK (called when already up to date)."""
    folder = directory or get_apk_directory()
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if not name.endswith(".apk"):
            continue
        path = os.path.join(folder, name)
        try:
            os.remove(path)
            logger.info("Deleted unused APK: %s", path)
        except OSError:
            logger.exception("Could not delete unused APK: %s", path)


def fetch_contributors(limit=CONTRIBUTORS_LIMIT):
    """GitHub logins of the release's contributors, the owner included.

    The result is cached for the process lifetime; a bot or a failing API must
    not break the update screen.
    """
    global _contributors_cache
    if _contributors_cache is not None:
        return list(_contributors_cache)
    fallback = [OWNER]
    try:
        response = requests.get(
            CONTRIBUTORS_API_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "Melo-Updater"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        names = []
        for entry in payload if isinstance(payload, list) else []:
            if not isinstance(entry, dict):
                continue
            login = str(entry.get("login") or "").strip()
            if not login or login in names:
                continue
            if str(entry.get("type") or "").lower() == "bot":
                continue
            if login.endswith("[bot]"):
                continue
            names.append(login)
        if OWNER not in names:
            names.insert(0, OWNER)
        _contributors_cache = names[:limit]
        return list(_contributors_cache)
    except Exception:
        logger.info("Could not load contributors", exc_info=True)
        return fallback


# --------------------------------------------------------------------------- #
# The object the view model talks to                                          #
# --------------------------------------------------------------------------- #
class UpdateRepository:
    """A small seam over the module functions, for the view model and tests."""

    def check_for_update(self, installed_version=None, supported_abis=None):
        try:
            return check_for_update(installed_version, supported_abis)
        except Exception as error_checking_update:
            logger.exception("Update check failed: %s", error_checking_update)
            return None

    def get_installed_version(self):
        return get_installed_version()

    def get_supported_abis(self):
        return get_supported_abis()

    def has_update_api_override(self):
        return has_update_api_override()

    def get_apk_path(self, filename, directory=None):
        return get_apk_path(filename, directory)

    def download_apk(self, url, filename="melo-update.apk",
                     progress_callback=None, cancel_event=None):
        return download_apk(url, filename, progress_callback, cancel_event)

    def apk_is_valid(self, path, expected_size):
        return apk_is_valid(path, expected_size)

    def do_android_install(self, apk_path):
        return do_android_install(apk_path)

    def fetch_contributors(self, limit=CONTRIBUTORS_LIMIT):
        return fetch_contributors(limit)

    def find_and_delete_unused_apks(self, latest_version=None):
        return find_and_delete_unused_apks(latest_version)
