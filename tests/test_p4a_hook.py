"""The p4a hook that adds the FileProvider to the built dist's manifest.

AGP 8 removed the manifest's ``package`` attribute, so the hook has to read
the package id from ``build.gradle``'s ``namespace`` instead. These tests pin
both shapes plus the idempotency of a profile rebuild.
"""

import importlib.util
from pathlib import Path

import pytest

HOOK_PATH = (Path(__file__).resolve().parent.parent
             / "app_src" / "android" / "p4a" / "hook.py")


def _load_hook():
    spec = importlib.util.spec_from_file_location("melo_p4a_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST_WITHOUT_PACKAGE = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
      android:versionCode="10241"
      android:versionName="0.0.1">
    <application android:label="@string/app_name"
                 android:debuggable="true">
    </application>
</manifest>
"""

MANIFEST_WITH_PACKAGE = MANIFEST_WITHOUT_PACKAGE.replace(
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android"',
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
    '      package="io.github.fector101.melo"',
)

BUILD_GRADLE = """android {
    namespace 'io.github.fector101.melo'
    compileSdkVersion 36
    defaultConfig {
        minSdkVersion 24
        targetSdkVersion 36
    }
}
"""


@pytest.fixture
def dist(tmp_path):
    """A minimal dist directory shaped like <dist>/src/main/AndroidManifest.xml."""
    main = tmp_path / "src" / "main"
    main.mkdir(parents=True)
    (tmp_path / "build.gradle").write_text(BUILD_GRADLE, encoding="utf-8")
    return tmp_path


def _write_manifest(dist, text):
    path = dist / "src" / "main" / "AndroidManifest.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _disable_network_config(hook, monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "NETWORK_SECURITY_CONFIG",
                        tmp_path / "does-not-exist.xml")


def test_namespace_from_gradle_is_used_when_manifest_has_no_package(
        dist, monkeypatch, tmp_path):
    hook = _load_hook()
    _disable_network_config(hook, monkeypatch, tmp_path)
    manifest = _write_manifest(dist, MANIFEST_WITHOUT_PACKAGE)

    hook._inject_file_provider(manifest)

    text = manifest.read_text(encoding="utf-8")
    assert 'android:name="androidx.core.content.FileProvider"' in text
    assert 'android:authorities="io.github.fector101.melo.fileprovider"' in text
    assert 'android:resource="@xml/file_paths"' in text
    assert "networkSecurityConfig" not in text


def test_manifest_package_attribute_still_wins(dist, monkeypatch, tmp_path):
    hook = _load_hook()
    _disable_network_config(hook, monkeypatch, tmp_path)
    manifest = _write_manifest(dist, MANIFEST_WITH_PACKAGE)

    hook._inject_file_provider(manifest)

    text = manifest.read_text(encoding="utf-8")
    assert 'android:authorities="io.github.fector101.melo.fileprovider"' in text


def test_application_id_wins_over_namespace(dist, monkeypatch, tmp_path):
    hook = _load_hook()
    _disable_network_config(hook, monkeypatch, tmp_path)
    (dist / "build.gradle").write_text(
        BUILD_GRADLE.replace("defaultConfig {",
                             "defaultConfig {\n        applicationId 'com.example.app'"),
        encoding="utf-8")
    manifest = _write_manifest(dist, MANIFEST_WITHOUT_PACKAGE)

    hook._inject_file_provider(manifest)

    text = manifest.read_text(encoding="utf-8")
    assert 'android:authorities="com.example.app.fileprovider"' in text


def test_running_twice_does_not_duplicate_the_provider(
        dist, monkeypatch, tmp_path):
    hook = _load_hook()
    _disable_network_config(hook, monkeypatch, tmp_path)
    manifest = _write_manifest(dist, MANIFEST_WITHOUT_PACKAGE)

    hook._inject_file_provider(manifest)
    first = manifest.read_text(encoding="utf-8")
    hook._inject_file_provider(manifest)

    assert manifest.read_text(encoding="utf-8") == first
    assert first.count("androidx.core.content.FileProvider") == 1


def test_network_security_config_is_added_only_when_present(
        dist, monkeypatch, tmp_path):
    hook = _load_hook()
    config = tmp_path / "network_security_config.xml"
    config.write_text("<network-security-config/>", encoding="utf-8")
    monkeypatch.setattr(hook, "NETWORK_SECURITY_CONFIG", config)
    manifest = _write_manifest(dist, MANIFEST_WITHOUT_PACKAGE)

    hook._inject_file_provider(manifest)

    text = manifest.read_text(encoding="utf-8")
    assert ('android:networkSecurityConfig="@xml/network_security_config"'
            in text)
    assert '<application android:networkSecurityConfig=' in text


def test_missing_package_and_gradle_is_a_hard_error(
        dist, monkeypatch, tmp_path):
    hook = _load_hook()
    _disable_network_config(hook, monkeypatch, tmp_path)
    (dist / "build.gradle").unlink()
    manifest = _write_manifest(dist, MANIFEST_WITHOUT_PACKAGE)

    with pytest.raises(RuntimeError, match="Could not find the app package"):
        hook._inject_file_provider(manifest)
