[app]

title = Melo
package.name = melo
package.domain = io.github.fector101
author = Fabian © Copyright Info
version = 0.0.1


source.dir = app_src
p4a.bootstrap = sdl3
requirements = python3, kivy==master, https://github.com/Fector101/android_notify/archive/main.zip


osx.python_version = 3
osx.kivy_version = 1.9.1


fullscreen = 0
orientation = all
android.permissions = INTERNET, POST_NOTIFICATIONS, (name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=32), READ_MEDIA_AUDIO


android.gradle_dependencies = io.github.fector101:android-notify-music-bridge:1.0.1
android.enable_androidx = True


android.api = 36
android.ndk = 29
p4a.branch = develop


android.archs = arm64-v8a, armeabi-v7a
android.release_artifact = apk
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
