# Developing Melo

Melo is a lightweight music player for Android, written in pure Kivy.
It displays all the audio files in your device and plays them with a media notification.


This document is the map of the codebase: i put this together to make development process easier

---

## 1. Codebase structure
```
Melo/
├── buildozer.spec         specifications for buildozer (do not touch casually)
├── app_src/               contains all the files that actually go into APK
│   ├── main.py            the composition root: builds and wires viewmodel to UI
│   ├── core/              platform glue (JVM, window insets)
│   ├── models/            the domain model (Track)
│   ├── repositories/      device access (MediaStore, artwork, audio, notification)
│   ├── viewmodels/        observable state + commands (library, player)
│   └── ui/                widgets, the screen and the KV rules
└── tests/                 pytest suite
```

`app_src/` is the working root, That's why every import inside the app is absolute
(`from models.track import Track`), and why the tests put `app_src/` on
`sys.path`.

---

## 2. Running it

### On the desktop

To make room for logical tests and possible additions of other platforms, The Android MediaStore scan returns an empty
list, the artwork extractor does nothing and the JVM calls are skipped.

Melo uses kivy 3.0.0.dev0 for audio feature to work properly, I'm currently using an editable install of kivy pulled straight from master for development, it lives in `app_src`, If you encounter issues with the Kivy import, ensure that the editable install is correctly set up, 

If `import kivy` fails with `ModuleNotFoundError`, the point to the kivy installed environment which contains yours

### On Android

```shell
buildozer android debug
```

The APK lands in `bin/melo-0.0.1-<arch>-debug.apk`.

What the build does:

| Setting | Meaning |
| --- | --- |
| `source.dir = app_src` | only `app_src/` is packaged - `tests/` stays out of the APK |
| `p4a.bootstrap = sdl3` | SDL3 required for kivy3 |
| `requirements = kivy==master, android_notify main.zip` | Kivy from master, `android_notify` from GitHub `main` |
| `android.permissions` | `INTERNET`, `POST_NOTIFICATIONS`, `READ_MEDIA_AUDIO` (+ legacy `READ_EXTERNAL_STORAGE` up to API 32) |
| `android.gradle_dependencies` | `android-notify-music-bridge` - helps send the media notification clicks to Python callback functions |

Without a local toolchain, `.github/workflows/android-debug.yml` builds debug
APKs on GitHub: *Actions → Debug APK → Run workflow*, pick an ABI (`all` runs
both). Each job uploads `melo-debug-<arch>` with
`melo-<version>-<arch>-debug-<sha>.apk`, its `.sha256`, and a `build-info.txt`.
Nothing is tagged or published.

- A cold run is ~25-35 min. The Android SDK/NDK are cached; the p4a dist is
  not, because the spec builds `kivy==master` and `p4a.branch=develop` and a
  cached dist would pin whatever those were when the cache was written.
- The APK is signed with the runner's own debug key, so it will **not** install
  over a locally built debug APK (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`).
  Uninstall first, or add a `DEBUG_KEYSTORE_BASE64` repository secret holding
  base64 of your `~/.android/debug.keystore` so both machines share a key.
- Tick `cleartext` to inject the gitignored `network_security_config.xml` into
  the build, which is what lets `scripts/device_self_update_test.py` talk to a
  laptop-hosted release server. Leave it off otherwise.

---

## 3. The architecture
Rule of thumb: UI speaks to Viewmodel, Viewmodel speaks to Repository. UI and Repository never come in contact except through Viewmodel

The code is split into five layers that only depend downwards.

```
                 ┌─────────────────────────────────────────┐
                 │                  ui/                   │  widgets, screen, KV
                 │   LibraryScreen ──binds──> ViewModels   │
                 └──────────────────────┬──────────────────┘
                                        │ commands
                 ┌──────────────────────▼──────────────────┐
                 │              viewmodels/                │  observable state
                 │   LibraryViewModel    PlayerViewModel    │
                 └──────────────────────┬──────────────────┘
                                        │
                 ┌──────────────────────▼──────────────────┐
                 │             repositories/               │  device access
                 │  Library  Artwork  Permissions  Playback│
                 └──────────────────────┬──────────────────┘
                                        │
                 ┌──────────────────────▼──────────────────┐
                 │   core/ (JVM, insets)   models/ (Track) │
                 └─────────────────────────────────────────┘
```

The rules, in one sentence each:

- **`ui/` never imports a repository.** The screen talks to the view models.
- **`viewmodels/` never imports `ui/`.** They are plain `EventDispatcher`s and
  know nothing about widgets.
- **`repositories/` never import `ui/`.** They are the only layer that talks
  to Android (MediaStore, the JVM, the audio engine).
- **`models/` is pure data.** No Kivy, no Android - so any process layer can rely
  on it.
- **`main.py` is the only file that knows all the layers.** It builds the
  repositories, the view models and the screen, and hands them to each other.

### The two view models

**`LibraryViewModel`** owns the list of tracks and the scan flow.

| Property | Meaning |
| --- | --- |
| `tracks` | the `Track` objects of the device, in display order |
| `status_text` | the line under the "Your Library" heading |
| `is_scanning` | true while a scan runs (the FAB is disabled) |
| event `on_artwork_ready` | `(path, art)` - a cover was extracted |

Commands: `scan()`, `set_status(text)`, `track_by_path(path)`,
`cached_artwork(path)`, `load_artwork(tracks)`.

**`PlayerViewModel`** owns what is playing and the transport.

| Property | Meaning |
| --- | --- |
| `current_track` | the loaded `Track` (or `None`) |
| `title` / `artist` / `art` | what the player bar shows |
| `is_playing` | whether the engine is playing |
| `position` / `duration` | seconds |
| `loop_enabled` | repeat the current track |
| `is_seeking` | the user is dragging the seek bar |

Commands: `play_track(track)`, `toggle_play_pause()`, `next_track()`,
`previous_track()`, `toggle_loop()`, `seek(seconds)`, `set_seeking(bool)`,
`start()` / `stop()` (the ticker).

Both are `kivy.event.EventDispatcher` + `Property`, so the UI can bind to
them instead of being updated by hand.

### The repositories

| Repository | Answers | On the desktop |
| --- | --- | --- |
| `LibraryRepository` | "which audio files are on the device?" | `scan()` returns `[]` |
| `ArtworkRepository` | "what is the cover of this file?" | `""` (no JVM) |
| `PermissionsRepository` | "may I read the audio library?" | `False` / `True` for the manifest check |
| `PlaybackRepository` | "play / pause / seek this file" | works, with the desktop audio provider |

`PlaybackRepository` also owns the `MediaNotification`. **Nothing above the
repository knows that a notification exists** - the app never imports
`android_notify` for playback.

---

## 4. The three flows

### Startup

```
MeloApp.build()
  |- Window.clearcolor = BG, load_kv_files()
  |- the repositories, the view models, the screen
  |- player_view_model.start()        (the 0.25s ticker)
  |- attach_insets(root_ui)           (no-op off Android)
  `- Clock.schedule_once(self._start, 2)
       `- 2s later: library_view_model.scan()   (the permission dialog needs
                                                the activity to be up)
```

`on_stop` cancels the ticker and releases the audio engine and the
notification. Off Android the window is set to 400x860 so the layout looks
roughly like on the phone.

### Scanning

```
FAB tapped
  -> LibraryScreen._on_scan
  -> LibraryViewModel.scan()
       |- not on Android      -> status "Scanning needs Android (...)"
       |- permission missing  -> ask, then continue on the answer
       `- otherwise           -> _start_scan()
                                   |- worker thread: LibraryRepository.scan()
                                   `- Clock.schedule_once -> _on_scan_done()
                                        |- tracks = [...]
                                        |- status "N songs added"
                                        `- load_artwork(tracks)
```

The scan runs on a worker thread because it queries MediaStore. The result
comes back through `Clock.schedule_once`, so the UI is only touched on the
Kivy thread.

### Cover art

```
LibraryViewModel.load_artwork(tracks)
  -> worker thread: ArtworkRepository.extract(path) per track
       |- MediaMetadataRetriever (JVM) pulls the embedded picture
       `- it is written to <user_data_dir>/art_cache/<hash>.jpg
  -> Clock.schedule_once -> _on_artwork_ready(path, art)
  -> dispatch("on_artwork_ready", path=..., art=...)
  -> LibraryScreen._on_artwork_ready
       |- patch the row dict
       `- songs.refresh_from_data()
```

The worker is abandoned when a newer scan starts (`_art_generation`), so a
slow extraction cannot overwrite a fresh one.

### Playback

```
row tapped -> SongRow.on_release -> on_select(path)
  -> LibraryScreen._on_row_selected -> PlayerViewModel.play_track(track)
  -> _load_current()
       |- PlaybackRepository.load(path)      (the audio engine)
       |- set_loop(), play()
       |- set_now_playing(title, artist)    (the notification)
       `- _refresh_for_current()             (title, artist, cover, position, status)
```

The progress bar is kept in sync by a ticker (`Clock.schedule_interval`,
every 0.25s); the ticker only reads the position. Kivy's audio API has **no
`on_complete` event**, so `KivySoundController` treats `Sound.on_stop` as the
end of a track: the sound stopped on its own and the position is at the
length. That callback (`_on_track_end`) restarts the track when looping,
advances otherwise, and stops at the end of the playlist.

---

## 5. The UI layer

### The KV rules

Six files in `app_src/ui/kv/`, loaded by `ui.load_kv_files()` (absolute
paths, because on Android the working directory is not the app directory):

| File | Styles |
| --- | --- |
| `library_screen.kv` | the root: heading, status line, list, FAB |
| `player.kv` | the player bar: cover, title, transport, seek bar |
| `song_row.kv` | one row of the list |
| `art.kv` | the rounded cover tile (with the note glyph as fallback) |
| `fab.kv` | the floating scan button |
| `icons.kv` | the vector glyphs (play, pause, prev, next, repeat, note) |

Two rules of thumb:

- **No Python strings in KV.** `#:import THEME ui.theme` and
  `#:import format_duration ui.format.format_duration` pull helpers in; the
  colours live in `ui/theme.py`.
- **No `app.` in KV.** The old code used `app.accent` and `app.previous_track()`.
  Now the KV only describes *what* it looks like, and `library_screen.py`
  binds the behaviour in Python.

### The widgets

| Widget | What it is |
| --- | --- |
| `SongRow` | a row of the list; `RecycleDataViewBehavior` so the list stays fast with hundreds of tracks |
| `Player` | the bar at the bottom; it only holds what it shows |
| `FillSlider` | the seek bar; reports a drag so the ticker keeps its hands off |
| `Art` | the rounded cover tile; falls back to a note glyph |
| `TransportIcon` / `Icon` | the glyphs, drawn on the canvas (no image assets) |
| `Fab` | the floating scan button |

`ui/widgets/__init__.py` imports every widget module **on purpose**: the
import is what registers the classes in Kivy's `Factory`, which is what makes
`viewclass: "SongRow"` work in the KV. `ui/screens/library_screen.py` imports
`ui.widgets` explicitly so the dependency is visible.

### The screen

`ui/screens/library_screen.py` is the only place where the view models and
the widgets meet. It:

- binds to the view model properties and pushes the values into the widgets
  (`_on_player_state`, `_on_position`, `_on_tracks`, `_on_status_text`),
- wires the buttons to the view model commands (`_on_previous`,
  `_on_next`, `_on_toggle_play_pause`, `_on_toggle_loop`, `_on_seek`,
  `_on_scan`),
- builds the row dicts of the `RecycleView` and patches them when the cover
  art arrives.

The rows are plain dicts. A row carries the display values **and** the
`on_select` callback:

```python
{
    "title": track.display_title,
    "artist": track.display_artist,
    "duration": format_duration(track.duration_seconds),
    "path": track.path,
    "art": self.library.cached_artwork(track.path),
    "active": track.path == active_path,
    "on_select": self._on_row_selected,
}
```

`RecycleView` copies every key of that dict onto the row widget with a plain
`setattr` (`RecycleDataViewBehavior.refresh_view_attrs`), which is why the
callback can travel with the data - and why a recycled row always points at
the right track.

---

## 6. Recipes

### "I want to change a colour"

`app_src/ui/theme.py`. The KV files import it as `THEME`. Do not sprinkle
hex values into the KV.

### "I want to add a column to the row (e.g. the album)"

1. `models/track.py`: the `Track` already has an `album` field.
2. `repositories/library_repository.py`: read the column in the projection.
3. `ui/screens/library_screen.py` `_on_tracks`: add the key to the row dict.
4. `ui/widgets/song_row.py`: add the property.
5. `ui/kv/song_row.kv`: add the label.

### "I want to add a button to the player bar"

1. `ui/kv/player.kv`: add the widget and give it an `id`.
2. `ui/screens/library_screen.py` `_bind_widgets`: bind its `on_release`.
3. `viewmodels/player_view_model.py`: add the command.
4. `repositories/playback_repository.py`: if it needs the engine, add a
   method there - the view model must not know about the engine.

### "I want to read something else from the device"

Add a method to a repository (or a new repository), expose it through a view
model, and bind it in the screen. Never let the screen call a repository
directly.

### "I want to change the behaviour of the scan"

`LibraryViewModel.scan()` is the single entry point; the worker is
`_start_scan()`. The repository only knows how to *list* the files.

### "I want a new screen"

Nothing in the app is a `ScreenManager` today - `main.py` returns one root
widget. Add a `ScreenManager` as the root and keep the layers: the screen
still only talks to the view models.

---

## 7. Tests

```shell
cd /home/fabian/Documents/Melo
python3 -m pytest tests/ -q         # the test suite 
python3 -m compileall -q app_src     # syntax check
```

| File | Covers |
| --- | --- |
| `tests/test_repositories.py` | the model, the formatting, the repositories off Android |
| `tests/test_library_view_model.py` | the scan flow, the permission flow, the artwork event |
| `tests/test_player_view_model.py` | transport commands, the ticker, the end of a track |
| `tests/test_ui_smoke.py` | the screen: the widgets exist, the rows are built, the buttons work |

`tests/conftest.py` provides the fakes (`FakePlayback`, `FakeArtwork`,
`FakeLibrary`, `FakePermissions`) and the fixtures `immediate_clock` and
`on_android`.

Two things to know when writing a test:

- **Anything that goes through a `@mainthread` callback needs the
  `immediate_clock` fixture.** In Kivy 3.0 `@mainthread` *always* defers the
  call to the next frame - there is no "we are already on the main thread"
  shortcut - so without the fixture the callback never runs and the test
  fails in a confusing way.
- **Buttons can be triggered without a touch**:
  `view.ids.player_bar.ids.next_button.dispatch("on_release", None)`.
  `ButtonBehavior.on_release` is a no-op, so `None` is safe.

---

## 8. Traps

These are the things that cost time. All of them are real.

1. **MediaStore `_data` is hidden on Android 10+.** The scan reads the file
   path column, which needs "All Files Access". Without it the list is empty
   and the status line explains it. Switching to `content://` URIs would fix
   this, but Kivy's `SoundLoader` only plays file paths - that is the trade
   the current design makes.

2. **`SoundLoader.load()` does not fail loudly.** For a file it cannot open,
   Kivy logs `Unable to load ...` and still returns a sound object. A
   `True` return value is not proof that the file is playable.

3. **The UI may only change after a successful load.** `play_track()` and
   `next_track()` move the index and load; the title, the artist, the cover
   and the highlighted row are updated by `_refresh_for_current()`, which
   runs only after the load succeeded. Otherwise a failed load would leave
   the old track's title on screen.

4. **Property writes belong on the Kivy thread.** The native completion
   callback runs on an Android UI thread; it may only touch the audio
   engine. Everything visible is refreshed from a `Clock.schedule_once`
   callback.

5. **`@mainthread` always defers** (see the tests above).

6. **`android_notify` on the desktop is older than the one on the device.**
   The installed `android-notify 1.61.10` has no `MediaNotification` and no
   `MediaPermissionHandler`; the device gets the newer `main.zip` from
   GitHub. Both imports are therefore guarded, and the desktop logs
   "no media notification support". That warning is expected off Android
   (it disappears when the newer vendored copy happens to be on the path).

7. **The notification is fed by hand.** `KivySoundController` has no
   `bind`/`events`, so `MediaNotification` cannot subscribe to the playback
   state. Every app-driven change calls `sync_notification()` explicitly.
   The notification's own buttons come back through
   `set_transport_callbacks(on_next=..., on_previous=...)`, and their effect
   on the UI shows up on the next ticker pass.

8. **SDL3 stops the audio when the activity pauses.** Kivy's default audio
   provider order would pick SDL, which suspends the device when the app is
   left or the screen turns off. Melo asks for the `android` provider
   (`MediaPlayer`) explicitly and sets a partial wake lock on it.

---

## 9. Where the project could go next

The current design is deliberately small: one screen, one playlist, no
settings. Natural next steps, in the order they would pay off:

- **Shuffle and repeat-all.** The player view model already owns the
  playlist order and the loop flag; shuffle is a second order of the same
  list.
- **A queue / "play next".** `PlayerViewModel.next_track()` walks a list -
  it could walk a queue instead.
- **content:// URIs.** That would fix the empty library on modern Android,
  but it needs an audio engine that can play a URI (the `android` provider
  can: `MediaPlayer.setDataSource(context, uri)`).
- **A background service.** Playback currently lives in the app process; a
  `Service` would let the music survive the app being swiped away.
- **Settings.** A theme file (`ui/theme.py`) and the loop flag are already
  the natural candidates for a first screen.

---

