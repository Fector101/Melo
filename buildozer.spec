[app]

title = Melo
package.name = melo
package.domain = io.github.fector101
author = Fabian © Copyright Info
version = 0.0.1


source.dir = app_src
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,json,xml,wav
source.exclude_dirs = bin, venv, .buildozer, __pycache__, .idea, .pytest_cache, tests, .facts, .github, dist, build
p4a.bootstrap = sdl3
requirements = python3, kivy==master, requests
#, https://github.com/Fector101/android_notify/archive/main.zip


osx.python_version = 3
osx.kivy_version = 1.9.1


fullscreen = 0
orientation = all
android.permissions = INTERNET, POST_NOTIFICATIONS, (name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=32), READ_MEDIA_AUDIO, REQUEST_INSTALL_PACKAGES, android.permission.WAKE_LOCK


android.gradle_dependencies = androidx.core:core:1.12.0, io.github.fector101:android-notify-music-bridge:1.0.1
android.enable_androidx = True
android.add_resources = %(source.dir)s/android/res
p4a.hook = %(source.dir)s/android/p4a/hook.py


android.api = 36
android.ndk = 29
p4a.branch = develop


android.archs = arm64-v8a, armeabi-v7a
android.release_artifact = apk
android.allow_backup = True


# One ABI per release job. Build with:
#   buildozer --profile arm64-v8a android release
#   buildozer --profile armeabi-v7a android release
[app@arm64-v8a]
android.archs = arm64-v8a

[app@armeabi-v7a]
android.archs = armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
