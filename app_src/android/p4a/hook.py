"""A p4a hook for the manifest changes Melo needs.

The updater hands the downloaded APK to Android's package installer through a
``FileProvider``. The provider itself is declared here (in the built dist's
manifest) instead of in a checked-in ``AndroidManifest.tmpl.xml`` so the
authority stays in sync with ``package.domain`` + ``package.name``.

A locally created ``res/xml/network_security_config.xml`` is also honoured when
present. That file is gitignored on purpose: it lets a debug build reach a
laptop-hosted release server over plain HTTP, while a clean checkout (CI and
release builds) ships with cleartext HTTP disabled.

The hook is idempotent: a profile rebuild reuses the dist directory, and the
provider or the network config must not be added twice.
"""

import re
from pathlib import Path

PACKAGE_RE = re.compile(r'\bpackage="([^"]+)"')
NAMESPACE_RE = re.compile(r"^\s*namespace\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
APPLICATION_ID_RE = re.compile(
    r"^\s*applicationId\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
APPLICATION_RE = re.compile(r"<application\b")

FILE_PROVIDER = """
<provider
    android:name="androidx.core.content.FileProvider"
    android:authorities="{authority}"
    android:exported="false"
    android:grantUriPermissions="true">
    <meta-data
        android:name="android.support.FILE_PROVIDER_PATHS"
        android:resource="@xml/file_paths" />
</provider>
"""

NETWORK_SECURITY_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "res" / "xml" / "network_security_config.xml"
)
NETWORK_SECURITY_ATTRIBUTE = (
    'android:networkSecurityConfig="@xml/network_security_config"'
)


def _find_package(manifest_path, content):
    """The app's package id.

    Older p4a templates put it in the manifest's ``package`` attribute. AGP 8
    (p4a with Gradle 8.11) forbids that attribute and moves it to the
    ``namespace`` in the dist's ``build.gradle``; ``applicationId`` wins if a
    template ever sets one.
    """
    match = PACKAGE_RE.search(content)
    if match is not None:
        return match.group(1)

    # <dist>/src/main/AndroidManifest.xml -> <dist>
    dist_dir = manifest_path.parents[2]
    gradle_path = dist_dir / "build.gradle"
    if gradle_path.exists():
        gradle = gradle_path.read_text(encoding="utf-8")
        for pattern in (APPLICATION_ID_RE, NAMESPACE_RE):
            match = pattern.search(gradle)
            if match is not None:
                return match.group(1)
    return None


def _inject_file_provider(manifest_path):
    manifest_path = Path(manifest_path)
    content = manifest_path.read_text(encoding="utf-8")

    package = _find_package(manifest_path, content)
    if not package:
        raise RuntimeError(
            "Could not find the app package in "
            f"{manifest_path} or its build.gradle. Refusing to build without "
            "a FileProvider authority derived from it."
        )
    authority = package + ".fileprovider"

    changed = False

    if ('android:name="androidx.core.content.FileProvider"' not in content
            and f'android:authorities="{authority}"' not in content):
        if "</application>" not in content:
            raise RuntimeError(
                f"Could not find </application> in {manifest_path}; "
                "cannot add the FileProvider."
            )
        provider = FILE_PROVIDER.format(authority=authority)
        content = content.replace("</application>",
                                  provider + "\n</application>", 1)
        changed = True
        print(f"Added FileProvider {authority} to {manifest_path}")
    else:
        print(f"FileProvider {authority} already present in {manifest_path}")

    if NETWORK_SECURITY_CONFIG.exists():
        if NETWORK_SECURITY_ATTRIBUTE in content:
            print(f"Network security config already present in {manifest_path}")
        else:
            content, count = APPLICATION_RE.subn(
                "<application " + NETWORK_SECURITY_ATTRIBUTE,
                content, count=1)
            if count != 1:
                raise RuntimeError(
                    f"Could not find <application in {manifest_path}; "
                    "cannot enable the local network security config."
                )
            changed = True
            print(f"Enabled {NETWORK_SECURITY_CONFIG} for local HTTP testing")
    else:
        print("No network security config; keeping cleartext HTTP disabled")

    if changed:
        manifest_path.write_text(content, encoding="utf-8")


def after_apk_build(toolchain):
    """p4a calls this in the dist directory, before Gradle assembles the APK."""
    manifest_path = (Path(toolchain._dist.dist_dir)
                     / "src" / "main" / "AndroidManifest.xml")
    _inject_file_provider(manifest_path)
