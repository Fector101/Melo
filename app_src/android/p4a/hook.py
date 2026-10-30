# For In App Updater
# hook.py for FileProvider and security config

from pathlib import Path


package = "io.github.fector101.melo"

FILE_PROVIDER = f"""
<provider
    android:name="androidx.core.content.FileProvider"
    android:authorities="{package}.fileprovider"
    android:exported="false"
    android:grantUriPermissions="true">
    <meta-data
        android:name="android.support.FILE_PROVIDER_PATHS"
        android:resource="@xml/file_paths" />
</provider>
"""

NETWORK_SECURITY_CONFIG = Path(__file__).resolve().parent.parent / "res" / "xml" / "network_security_config.xml"
NETWORK_SECURITY_ATTRIBUTE = 'android:networkSecurityConfig="@xml/network_security_config"'



def _inject_file_provider(manifest_path):
    manifest_path = Path(manifest_path)
    content = manifest_path.read_text(encoding="utf-8")

    if 'android:name="androidx.core.content.FileProvider"' not in content:
        content = content.replace("</application>", FILE_PROVIDER + "\n</application>")
    else:
        print(f"FileProvider already present in {manifest_path}")

    if NETWORK_SECURITY_CONFIG.exists():
        if NETWORK_SECURITY_ATTRIBUTE in content:
            print(f"Network security config already present in {manifest_path}")
        else:
            content = content.replace("<application", "<application " + NETWORK_SECURITY_ATTRIBUTE, 1)
            print(f"Enabled {NETWORK_SECURITY_CONFIG} for local HTTP testing")
    else:
        print("No network security config; keeping cleartext HTTP disabled")

    manifest_path.write_text(content, encoding="utf-8")


def after_apk_build(toolchain):
    """p4a calls this in the dist directory, before Gradle assembles the APK."""
    manifest_path = Path(toolchain._dist.dist_dir) / "src" / "main" / "AndroidManifest.xml"
    _inject_file_provider(manifest_path)



#PACKAGE_RE = re.compile(r'\bpackage="([^"]+)"')
#NAMESPACE_RE = re.compile(r"^\s*namespace\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
#APPLICATION_ID_RE = re.compile(r"^\s*applicationId\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
#APPLICATION_RE = re.compile(r"<application\b")



#def _find_package(manifest_path, content):
   # """The app's package id.

 #   Older p4a templates put it in the manifest's ``package`` attribute. AGP 8
  #  (p4a with Gradle 8.11) forbids that attribute and moves it to the
   # ``namespace`` in the dist's ``build.gradle``; ``applicationId`` wins if a
    #template ever sets one.
  #  """
   # match = PACKAGE_RE.search(content)
  #  if match is not None:
 #       return match.group(1)

    # <dist>/src/main/AndroidManifest.xml -> <dist>
#    dist_dir = manifest_path.parents[2]
 #   gradle_path = dist_dir / "build.gradle"
  #  if gradle_path.exists():
      #  gradle = gradle_path.read_text(encoding="utf-8")
     #   for pattern in (APPLICATION_ID_RE, NAMESPACE_RE):
   #         match = pattern.search(gradle)
    #        if match is not None:
#                return match.group(1)
  #  return None
