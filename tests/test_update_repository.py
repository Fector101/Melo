"""The update repository and release model: no Kivy, no device needed."""

import json

import pytest
import requests

import repositories.update_repository as updater
from models.release import ReleaseAsset, parse_highlights
from repositories.update_repository import (DownloadCancelled, RestartDownload,
                                            _parse_assets, _resume_offset,
                                            apk_is_valid, asset_abi,
                                            check_for_update,
                                            find_and_delete_unused_apks,
                                            get_release_api_url,
                                            get_release_base_url,
                                            has_update_api_override, is_newer,
                                            select_asset)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #
class FakeResponse:
    """Just enough of ``requests.Response`` for the updater."""

    def __init__(self, status_code=200, headers=None, chunks=(), json_data=None,
                 text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks
        self._json = json_data
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, _chunk_size=8192):
        yield from self._chunks

    def json(self):
        return self._json


def release_payload(version="0.0.2", assets=None, body="", published="2026-11-01T12:00:00Z"):
    return {
        "tag_name": f"v{version}",
        "body": body,
        "html_url": f"https://github.com/Fector101/Melo/releases/tag/v{version}",
        "published_at": published,
        "assets": assets if assets is not None else [
            {"name": f"melo-v{version}-arm64-v8a.apk", "size": 48000000,
             "download_count": 12, "updated_at": "2026-10-01T12:00:00Z"},
            {"name": f"melo-v{version}-armeabi-v7a.apk", "size": 43000000,
             "download_count": 3, "updated_at": "2026-10-01T12:00:00Z"},
        ],
    }


def fake_network(monkeypatch, payload, raw_note="- Faster scans\n- Gapless playback"):
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url.endswith("/releases/latest"):
            return FakeResponse(json_data=payload)
        if "raw.githubusercontent.com" in url:
            if raw_note is None:
                return FakeResponse(status_code=404)
            return FakeResponse(text=raw_note)
        if "contributors" in url:
            return FakeResponse(json_data=[])
        raise AssertionError(url)

    monkeypatch.setattr(updater.requests, "get", fake_get)
    return calls


# --------------------------------------------------------------------------- #
# Versions and ABIs                                                           #
# --------------------------------------------------------------------------- #
def test_is_newer_compares_versions_numerically():
    assert is_newer("0.0.2", "0.0.1") is True
    assert is_newer("v0.0.2", "0.0.1") is True
    assert is_newer("0.0.1", "0.0.1") is False
    assert is_newer("1.0.0", "0.9.9") is True
    assert is_newer("0.0.10", "0.0.9") is True


def test_is_newer_falls_back_to_inequality_when_it_cannot_parse():
    assert is_newer("nightly", "0.0.1") is True
    assert is_newer("nightly", "nightly") is False


def test_asset_abi_reads_the_suffix():
    assert asset_abi("melo-v0.0.2-arm64-v8a.apk") == "arm64-v8a"
    assert asset_abi("melo-v0.0.2-armeabi-v7a.apk") == "armeabi-v7a"
    assert asset_abi("melo-v0.0.2-universal.apk") == "universal"
    assert asset_abi("melo-v0.0.2.apk") is None


def test_select_asset_follows_the_device_abi_order():
    assets = [
        ReleaseAsset("a-armeabi-v7a.apk", 1, "u", abi="armeabi-v7a"),
        ReleaseAsset("a-arm64-v8a.apk", 1, "u", abi="arm64-v8a"),
    ]
    selected = select_asset(assets, ("arm64-v8a", "armeabi-v7a"))
    assert selected.abi == "arm64-v8a"

    selected = select_asset(assets, ("armeabi-v7a", "arm64-v8a"))
    assert selected.abi == "armeabi-v7a"


def test_select_asset_prefers_a_universal_apk_as_the_last_resort():
    assets = [
        ReleaseAsset("a-arm64-v8a.apk", 1, "u", abi="arm64-v8a"),
        ReleaseAsset("a-universal.apk", 2, "u", abi="universal"),
    ]
    assert select_asset(assets, ("x86_64",)).abi == "universal"
    assert select_asset(assets, ()).abi == "universal"
    assert select_asset([], ("arm64-v8a",)) is None


# --------------------------------------------------------------------------- #
# Notes                                                                       #
# --------------------------------------------------------------------------- #
def test_highlights_are_parsed_from_markdown_bullets():
    text = "- **Faster** scans\n- [Gapless](https://example.com) playback\n- `UI` fixes"
    assert parse_highlights(text) == ["Faster scans", "Gapless playback", "UI fixes"]


def test_highlights_fall_back_to_prose_and_then_defaults():
    assert parse_highlights("What is new\nFaster scans") == [
        "What is new", "Faster scans"]
    assert parse_highlights("") == [
        "Performance improvements.", "Bug fixes.", "UI refinements."]


def test_highlights_are_limited():
    text = "\n".join(f"- Item {index}" for index in range(10))
    assert len(parse_highlights(text, limit=3)) == 3


# --------------------------------------------------------------------------- #
# Endpoint overrides                                                          #
# --------------------------------------------------------------------------- #
def test_the_endpoint_config_is_read_from_the_apk_directory(tmp_path,
                                                            monkeypatch):
    monkeypatch.delenv("MELO_UPDATE_API_URL", raising=False)
    monkeypatch.delenv("MELO_UPDATE_BASE_URL", raising=False)
    monkeypatch.setattr(updater, "get_apk_directory", lambda: str(tmp_path))
    (tmp_path / "update_endpoint.json").write_text(json.dumps({
        "api_url": "http://127.0.0.1:8000/releases/latest",
        "base_url": "http://127.0.0.1:8000/download",
    }), encoding="utf-8")

    assert get_release_api_url() == "http://127.0.0.1:8000/releases/latest"
    assert get_release_base_url() == "http://127.0.0.1:8000/download"
    assert has_update_api_override() is True


def test_a_base_url_alone_is_not_an_api_override(tmp_path, monkeypatch):
    monkeypatch.delenv("MELO_UPDATE_API_URL", raising=False)
    monkeypatch.delenv("MELO_UPDATE_BASE_URL", raising=False)
    monkeypatch.setattr(updater, "get_apk_directory", lambda: str(tmp_path))
    (tmp_path / "update_endpoint.json").write_text(json.dumps({
        "base_url": "http://127.0.0.1:8000/download",
    }), encoding="utf-8")

    assert get_release_api_url() == updater.DEFAULT_RELEASE_API_URL
    assert has_update_api_override() is False


def test_an_unreadable_endpoint_config_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("MELO_UPDATE_API_URL", raising=False)
    monkeypatch.setattr(updater, "get_apk_directory", lambda: str(tmp_path))
    (tmp_path / "update_endpoint.json").write_text("not json", encoding="utf-8")

    assert get_release_api_url() == updater.DEFAULT_RELEASE_API_URL


def test_the_environment_wins_over_the_endpoint_config(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "get_apk_directory", lambda: str(tmp_path))
    monkeypatch.setenv("MELO_UPDATE_API_URL", "http://env/api")
    monkeypatch.setenv("MELO_UPDATE_BASE_URL", "http://env/base")

    assert get_release_api_url() == "http://env/api"
    assert get_release_base_url() == "http://env/base"


# --------------------------------------------------------------------------- #
# The check                                                                   #
# --------------------------------------------------------------------------- #
def test_check_for_update_selects_the_asset_for_the_device(monkeypatch):
    monkeypatch.setenv("MELO_UPDATE_BASE_URL", "https://example.test/download")
    fake_network(monkeypatch, release_payload())

    release = check_for_update("0.0.1", ("arm64-v8a", "armeabi-v7a"))

    assert release is not None
    assert release.version == "0.0.2"
    assert release.tag == "v0.0.2"
    assert release.asset.name == "melo-v0.0.2-arm64-v8a.apk"
    assert release.asset.size == 48000000
    assert release.asset.downloads == 12
    assert release.asset.download_url == (
        "https://example.test/download/v0.0.2/"
        "melo-v0.0.2-arm64-v8a.apk")
    assert release.notes.startswith("- Faster scans")


def test_check_for_update_uses_the_other_supported_abi(monkeypatch):
    monkeypatch.setenv("MELO_UPDATE_BASE_URL", "https://example.test/download")
    fake_network(monkeypatch, release_payload())

    release = check_for_update("0.0.1", ("armeabi-v7a",))

    assert release.asset.name == "melo-v0.0.2-armeabi-v7a.apk"


def test_check_for_update_falls_back_to_the_release_body(monkeypatch):
    fake_network(monkeypatch, release_payload(body="- Body note"),
                 raw_note=None)

    release = check_for_update("0.0.1", ("arm64-v8a",))

    assert release.notes == "- Body note"


def test_check_for_update_returns_none_when_already_current(monkeypatch):
    payload = release_payload()
    payload["tag_name"] = "v0.0.1"
    fake_network(monkeypatch, payload)
    deleted = []
    monkeypatch.setattr(updater, "find_and_delete_unused_apks",
                        lambda version: deleted.append(version))

    assert check_for_update("0.0.1", ("arm64-v8a",)) is None
    assert deleted == ["0.0.1"]


def test_check_for_update_returns_none_without_a_matching_asset(monkeypatch):
    payload = release_payload(assets=[
        {"name": "melo-v0.0.2-x86_64.apk", "size": 1},
    ])
    fake_network(monkeypatch, payload)

    assert check_for_update("0.0.1", ("arm64-v8a",)) is None


def test_check_for_update_survives_a_network_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updater.requests, "get", fail)

    assert check_for_update("0.0.1", ("arm64-v8a",)) is None


def test_asset_urls_are_built_from_the_download_base(monkeypatch):
    monkeypatch.setenv("MELO_UPDATE_BASE_URL", "https://example.test/download/")
    assets = _parse_assets({
        "tag_name": "v0.0.2",
        "assets": [{"name": "melo-v0.0.2-arm64-v8a.apk", "size": "7",
                    "browser_download_url": "ignored"}],
    })

    assert assets[0].download_url == (
        "https://example.test/download/v0.0.2/melo-v0.0.2-arm64-v8a.apk")
    assert assets[0].size == 7


# --------------------------------------------------------------------------- #
# Downloads                                                                   #
# --------------------------------------------------------------------------- #
def test_a_download_writes_the_file_and_reports_progress(tmp_path, monkeypatch):
    seen = []

    response = FakeResponse(headers={"content-length": "6"},
                            chunks=[b"abc", b"def"])
    monkeypatch.setattr(updater.requests, "get",
                        lambda *_args, **_kwargs: response)

    path = updater.download_apk("https://example.test/x.apk", "update.apk",
                                progress_callback=seen.append,
                                directory=str(tmp_path))

    assert path == str(tmp_path / "update.apk")
    assert (tmp_path / "update.apk").read_bytes() == b"abcdef"
    assert seen == [50, 100]


def test_a_download_resumes_with_a_range_request(tmp_path, monkeypatch):
    (tmp_path / "update.apk").write_bytes(b"abcd")
    calls = []
    response = FakeResponse(
        status_code=206,
        headers={"content-length": "4", "Content-Range": "bytes 4-7/8"},
        chunks=[b"efgh"],
    )

    def fake_get(_url, headers=None, **_kwargs):
        calls.append(headers)
        return response

    monkeypatch.setattr(updater.requests, "get", fake_get)
    seen = []
    path = updater.download_apk("https://example.test/x.apk", "update.apk",
                                progress_callback=seen.append,
                                directory=str(tmp_path))

    assert path == str(tmp_path / "update.apk")
    assert calls == [{"Range": "bytes=4-"}]
    assert (tmp_path / "update.apk").read_bytes() == b"abcdefgh"
    assert seen == [100]


def test_a_cancelled_download_keeps_the_partial_file(tmp_path, monkeypatch):
    import threading

    cancel = threading.Event()

    def chunks():
        yield b"abcd"
        cancel.set()
        yield b"efgh"

    response = FakeResponse(headers={"content-length": "8"},
                            chunks=chunks())
    monkeypatch.setattr(updater.requests, "get",
                        lambda *_args, **_kwargs: response)

    with pytest.raises(DownloadCancelled):
        updater.download_apk("https://example.test/x.apk", "update.apk",
                             cancel_event=cancel, directory=str(tmp_path))

    assert (tmp_path / "update.apk").read_bytes() == b"abcd"


def test_a_server_that_replays_from_zero_restarts_the_download(tmp_path,
                                                               monkeypatch):
    (tmp_path / "update.apk").write_bytes(b"abcd")
    responses = [
        FakeResponse(status_code=200, headers={"content-length": "8"},
                     chunks=[b"abcdefgh"]),
        FakeResponse(status_code=200, headers={"content-length": "8"},
                     chunks=[b"abcdefgh"]),
    ]

    def fake_get(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(updater.requests, "get", fake_get)
    path = updater.download_apk("https://example.test/x.apk", "update.apk",
                                directory=str(tmp_path))

    assert path == str(tmp_path / "update.apk")
    assert (tmp_path / "update.apk").read_bytes() == b"abcdefgh"
    assert responses == []


def test_a_206_with_a_wrong_content_range_restarts(tmp_path, monkeypatch):
    path = tmp_path / "x.apk"
    path.write_bytes(b"abcd")
    response = FakeResponse(
        status_code=206,
        headers={"content-length": "8", "Content-Range": "bytes 0-7/8"},
        chunks=[b"abcdefgh"],
    )
    monkeypatch.setattr(updater.requests, "get",
                        lambda *_args, **_kwargs: response)

    with pytest.raises(RestartDownload):
        updater._download_apk_once("https://example.test/x.apk", str(path), 4)

    assert _resume_offset({"Content-Range": "bytes 4-7/8"}) == 4
    assert _resume_offset({"Content-Range": "bytes 0-7/8"}) == 0
    assert _resume_offset({}) is None


def test_a_download_failure_returns_none(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updater.requests, "get", fail)

    assert updater.download_apk("https://example.test/x.apk", "update.apk",
                                directory=str(tmp_path)) is None


def test_a_valid_apk_must_match_the_expected_size(tmp_path):
    path = tmp_path / "update.apk"
    path.write_bytes(b"1234")

    assert apk_is_valid(str(path), 4) == str(path)
    assert apk_is_valid(str(path), 5) is None
    assert apk_is_valid(str(tmp_path / "missing.apk"), 4) is None


def test_unused_apks_are_deleted_and_other_files_are_kept(tmp_path):
    (tmp_path / "one.apk").write_bytes(b"1")
    (tmp_path / "two.apk").write_bytes(b"2")
    (tmp_path / "notes.txt").write_text("keep")

    find_and_delete_unused_apks("0.0.2", directory=str(tmp_path))

    assert not (tmp_path / "one.apk").exists()
    assert not (tmp_path / "two.apk").exists()
    assert (tmp_path / "notes.txt").exists()


# --------------------------------------------------------------------------- #
# Install                                                                     #
# --------------------------------------------------------------------------- #
def test_installing_off_android_does_nothing(tmp_path):
    path = tmp_path / "update.apk"
    path.write_bytes(b"x")

    assert updater.do_android_install(str(path)) is False


def test_installing_uses_the_file_provider_first(tmp_path, monkeypatch):
    path = tmp_path / "update.apk"
    path.write_bytes(b"x")
    monkeypatch.setattr(updater, "on_android_platform", lambda: True)
    monkeypatch.setattr(updater, "install_apk15", lambda p: True)

    assert updater.do_android_install(str(path)) is True


def test_installing_falls_back_to_the_legacy_intent(tmp_path, monkeypatch):
    path = tmp_path / "update.apk"
    path.write_bytes(b"x")
    monkeypatch.setattr(updater, "on_android_platform", lambda: True)
    monkeypatch.setattr(updater, "install_apk15", lambda p: False)
    monkeypatch.setattr(updater, "install_apk", lambda p: True)

    assert updater.do_android_install(str(path)) is True


def test_installing_returns_false_when_both_paths_fail(tmp_path, monkeypatch):
    path = tmp_path / "update.apk"
    path.write_bytes(b"x")
    monkeypatch.setattr(updater, "on_android_platform", lambda: True)

    def fail(_path):
        raise RuntimeError("no installer")

    monkeypatch.setattr(updater, "install_apk15", fail)
    monkeypatch.setattr(updater, "install_apk", fail)

    assert updater.do_android_install(str(path)) is False


# --------------------------------------------------------------------------- #
# Contributors                                                                #
# --------------------------------------------------------------------------- #
def test_contributors_are_filtered_cached_and_owner_included(monkeypatch):
    monkeypatch.setattr(updater, "_contributors_cache", None)
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(json_data=[
            {"login": "bob", "type": "User"},
            {"login": "dependabot[bot]", "type": "Bot"},
            {"login": "Fector101", "type": "User"},
            {"login": "bob", "type": "User"},
        ])

    monkeypatch.setattr(updater.requests, "get", fake_get)

    assert updater.fetch_contributors() == ["bob", "Fector101"]
    assert updater.fetch_contributors() == ["bob", "Fector101"]
    assert len(calls) == 1


def test_contributors_fall_back_to_the_owner(monkeypatch):
    monkeypatch.setattr(updater, "_contributors_cache", None)

    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updater.requests, "get", fail)

    assert updater.fetch_contributors() == ["Fector101"]
