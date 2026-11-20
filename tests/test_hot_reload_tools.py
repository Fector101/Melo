"""Unit checks for the tools/ hot-reload pair (no device or adb required)."""

import importlib.util
import os
import sys
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"


def _load_by_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dhr = _load_by_path("melo_hot_reload_device", TOOLS_DIR / "hot_reload_device.py")
watcher = _load_by_path("melo_dev_hot_reload_watcher",
                        TOOLS_DIR / "dev_hot_reload.py")


@pytest.fixture()
def isolated_source(tmp_path, monkeypatch):
    monkeypatch.setattr(dhr, "source_root", lambda: str(tmp_path))
    return tmp_path


def _touch(root, rel, content="x"):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _snap(root):
    return dhr.scan_snapshot(str(root))


# --------------------------------------------------------------------------- #
# device poller: helpers                                                       #
# --------------------------------------------------------------------------- #

def test_melo_defaults():
    args = watcher.parse_args([])
    assert args.package == "io.github.fector101.melo"
    assert args.activity == "org.kivy.android.PythonActivity"
    assert Path(watcher.DEFAULT_SOURCE) == REPO_ROOT / "app_src"


def test_module_name_for_path_basic(isolated_source):
    path = isolated_source / "ui" / "screens" / "search_screen.py"
    assert dhr.module_name_for_path(str(isolated_source), str(path)) == \
        "ui.screens.search_screen"


def test_module_name_for_init_and_main(isolated_source):
    assert dhr.module_name_for_path(
        str(isolated_source), str(isolated_source / "utils" / "__init__.py")) == "utils"
    assert dhr.module_name_for_path(
        str(isolated_source), str(isolated_source / "main.py")) == "main"


def test_module_name_outside_root_or_not_py(isolated_source):
    assert dhr.module_name_for_path(str(isolated_source), "/etc/passwd.py") is None
    kv = isolated_source / "ui" / "x.kv"
    assert dhr.module_name_for_path(str(isolated_source), str(kv)) is None


def test_class_name_for_module():
    assert dhr.class_name_for_module("ui.screens.search_screen") == "SearchScreen"
    assert dhr.class_name_for_module("ui.widgets.song_row") == "SongRow"


def test_scan_skips_pycache_and_hidden(isolated_source):
    _touch(isolated_source, "ui/a.py")
    _touch(isolated_source, "ui/b.kv")
    _touch(isolated_source, "ui/__pycache__/a.cpython-312.pyc")
    _touch(isolated_source, ".hidden/x.py")
    assert set(_snap(isolated_source)) == {
        os.path.join("ui", "a.py"), os.path.join("ui", "b.kv")}


def test_diff_reports_change_add_remove(isolated_source):
    _touch(isolated_source, "a.py", "one")
    old = _snap(isolated_source)
    time.sleep(0.01)
    _touch(isolated_source, "a.py", "two")
    _touch(isolated_source, "new.py")
    new = _snap(isolated_source)
    diff = dhr.diff_snapshots(old, new)
    assert diff == {"changed": ["a.py"], "added": ["new.py"], "removed": []}
    _touch(isolated_source, "other.py")
    assert dhr.diff_snapshots(new, _snap(isolated_source))["added"] == ["other.py"]


def test_bucket_changes():
    buckets = dhr.bucket_changes(["ui/kv/a.kv", "main.py", "assets/x.png",
                                  "viewmodels/y.py"])
    assert buckets["kv"] == ["ui/kv/a.kv"]
    assert sorted(buckets["py"]) == ["main.py", "viewmodels/y.py"]
    assert buckets["other"] == ["assets/x.png"]


def test_sort_py_reload_order_screens_last(isolated_source):
    rels = [os.path.join("ui", "screens", "search_screen.py"),
            os.path.join("viewmodels", "library_view_model.py"),
            os.path.join("ui", "widgets", "song_row.py"),
            os.path.join("ui", "screens", "library_screen.py")]
    ordered = dhr.sort_py_reload_order(rels)
    assert set(ordered[-2:]) == {rels[0], rels[3]}
    assert ordered[0] == os.path.join("ui", "widgets", "song_row.py")


def test_kv_target_uses_melo_layout(isolated_source):
    reloader = dhr.DevHotReloader(str(isolated_source))
    assert reloader.kv_target(str(isolated_source / "ui/kv/search_screen.kv")) == \
        ("screen", "ui.screens.search_screen")
    assert reloader.kv_target(str(isolated_source / "ui/kv/widgets/song_row.kv")) == \
        ("widget", None)


def test_maybe_start_noop_without_marker(isolated_source, monkeypatch):
    monkeypatch.setattr(dhr, "_reloader_instance", None)
    assert dhr.maybe_start_dev_hot_reload() is None
    assert dhr._reloader_instance is None


def test_maybe_start_activates_and_is_idempotent(isolated_source, monkeypatch):
    monkeypatch.setattr(dhr, "_reloader_instance", None)
    _touch(isolated_source, dhr.MARKER_FILE_NAME)
    started = []
    monkeypatch.setattr(dhr.DevHotReloader, "start",
                        lambda self: started.append(self.root))
    first = dhr.maybe_start_dev_hot_reload()
    assert first is not None
    assert started == [str(isolated_source)]
    assert dhr.maybe_start_dev_hot_reload() is first
    assert started == [str(isolated_source)]


def test_reload_single_module_never_imports_unknown(isolated_source):
    dhr.DevHotReloader(str(isolated_source)).reload_modules(
        ["android/services/worker.py"])
    assert "android.services.worker" not in sys.modules


# --------------------------------------------------------------------------- #
# device poller: live screens                                                  #
# --------------------------------------------------------------------------- #

class FakeScreen:

    def __init__(self, library=None, player=None, **kwargs):
        self.library = library
        self.player = player
        self.extra = kwargs
        self.name = ""


class FakeManager:

    def __init__(self, screen):
        self.screens = [screen]
        self.current = screen.name
        self.transition = "original"
        self._screen_factories = {}
        self.library_view_model = object()
        self.player_view_model = object()
        self.search_screen = screen

    def get_screen(self, name):
        return next((s for s in self.screens if s.name == name), None)

    def remove_widget(self, widget):
        self.screens.remove(widget)

    def add_widget(self, widget):
        self.screens.append(widget)

    def register_screen(self, name, factory):
        self._screen_factories[name] = factory


def test_built_screen_modules_uses_manager(isolated_source, monkeypatch):
    old = FakeScreen()
    old.name = "search"
    manager = FakeManager(old)
    app = types.SimpleNamespace(screen_manager=manager)
    monkeypatch.setattr(dhr.App, "get_running_app", staticmethod(lambda: app))
    assert dhr.DevHotReloader(str(isolated_source)).built_screen_modules() == \
        ["ui.screens.search_screen"]


def test_rebuild_search_screen_swaps_live_instance(isolated_source, monkeypatch):
    old = FakeScreen()
    old.name = "search"
    manager = FakeManager(old)
    stale_factory = lambda: old  # noqa: E731
    manager._screen_factories["search"] = stale_factory
    app = types.SimpleNamespace(screen_manager=manager)
    monkeypatch.setattr(dhr.App, "get_running_app", staticmethod(lambda: app))
    module = types.ModuleType("ui.screens.search_screen")
    module.SearchScreen = FakeScreen
    monkeypatch.setitem(sys.modules, "ui.screens.search_screen", module)

    assert dhr.DevHotReloader(str(isolated_source)).rebuild_screen(
        "ui.screens.search_screen") is True
    fresh = manager.get_screen("search")
    assert fresh is not old
    assert fresh.library is manager.library_view_model
    assert fresh.player is manager.player_view_model
    assert manager.search_screen is fresh
    assert manager.current == "search"
    assert manager.transition == "original"
    assert "search" in manager._screen_factories
    assert manager._screen_factories["search"] is not stale_factory
    assert manager._screen_factories["search"]().library is manager.library_view_model


def test_rebuild_reseeds_state_and_preserves_screen_padding(
        isolated_source, monkeypatch):
    from kivy.event import EventDispatcher
    from kivy.properties import ListProperty, StringProperty

    class ObservableVM(EventDispatcher):
        tracks = ListProperty([])
        status_text = StringProperty("")

    class FakeContainer:
        def __init__(self, padding):
            self.padding = padding

    class BoundScreen:
        def __init__(self, library_view_model=None, padding=None, **kwargs):
            self.vm = library_view_model
            self.events = []
            self.inset_top = 24
            self.inset_bottom = 16
            self.ids = {"main_container":
                        FakeContainer(padding or [0, 0, 0, 0])}
            if library_view_model is not None:
                library_view_model.bind(tracks=self._on_tracks,
                                        status_text=self._on_status)

        def _on_tracks(self, _instance, tracks):
            self.events.append(("tracks", list(tracks)))

        def _on_status(self, _instance, value):
            self.events.append(("status", value))

        def apply_padding(self, inset_top, inset_bottom):
            self.inset_top = inset_top
            self.inset_bottom = inset_bottom
            self.ids["main_container"].padding = [
                0, inset_top, 0, inset_bottom]

    vm = ObservableVM(tracks=["a.mp3"], status_text="1 songs added")
    old = BoundScreen(vm, padding=[0, 24, 0, 16])
    old.name = "search"
    manager = FakeManager(old)
    manager.library_view_model = vm
    app = types.SimpleNamespace(screen_manager=manager)
    monkeypatch.setattr(dhr.App, "get_running_app", staticmethod(lambda: app))
    module = types.ModuleType("ui.screens.search_screen")
    module.SearchScreen = BoundScreen
    monkeypatch.setitem(sys.modules, "ui.screens.search_screen", module)

    assert dhr.DevHotReloader(str(isolated_source)).rebuild_screen(
        "ui.screens.search_screen") is True
    fresh = manager.get_screen("search")
    assert ("tracks", ["a.mp3"]) in fresh.events
    assert ("status", "1 songs added") in fresh.events
    assert fresh.inset_top == 24
    assert fresh.inset_bottom == 16
    assert fresh.ids["main_container"].padding == [0, 24, 0, 16]
    observers = vm.get_property_observers("tracks")
    assert not any(getattr(proxy(), "__self__", None) is old for proxy in observers)


def test_rebuild_skips_unopened_screen(isolated_source, monkeypatch):
    manager = FakeManager(FakeScreen())
    monkeypatch.setattr(dhr.App, "get_running_app",
                        staticmethod(lambda: types.SimpleNamespace(screen_manager=manager)))
    module = types.ModuleType("ui.screens.search_screen")
    module.SearchScreen = FakeScreen
    monkeypatch.setitem(sys.modules, "ui.screens.search_screen", module)
    assert dhr.DevHotReloader(str(isolated_source)).rebuild_screen(
        "ui.screens.search_screen") is False
    assert manager.screens[0].name != "search"


def test_reregister_widgets_replaces_factory_class():
    from kivy.factory import Factory
    from kivy.uix.widget import Widget

    class DummyWidget(Widget):
        pass

    DummyWidget.__module__ = "fake_widgets"
    module = types.ModuleType("fake_widgets")
    module.DummyWidget = DummyWidget
    try:
        dhr.DevHotReloader.reregister_widgets(module)
        assert Factory.classes["DummyWidget"]["cls"] is DummyWidget
    finally:
        Factory.unregister("DummyWidget")


def test_reload_screen_module_unloads_its_kv_first(isolated_source, monkeypatch):
    _touch(isolated_source, "ui/kv/search_screen.kv")
    module = types.ModuleType("ui.screens.search_screen")
    monkeypatch.setitem(sys.modules, "ui.screens.search_screen", module)
    monkeypatch.setattr(dhr.importlib, "reload", lambda m: m)
    unloaded = []
    fake_builder = types.SimpleNamespace(
        unload_file=lambda filename: unloaded.append(filename))
    monkeypatch.setitem(sys.modules, "kivy.lang",
                        types.SimpleNamespace(Builder=fake_builder))

    reloader = dhr.DevHotReloader(str(isolated_source))
    assert reloader.reload_modules(
        [os.path.join("ui", "screens", "search_screen.py")]) == \
        {"ui.screens.search_screen"}
    assert unloaded == [str(isolated_source / "ui" / "kv" / "search_screen.kv")]


def test_reload_kv_screen_returns_owner(isolated_source, monkeypatch):
    loaded = []
    monkeypatch.setattr(dhr, "Builder", None, raising=False)
    fake_builder = types.SimpleNamespace(
        unload_file=lambda filename: loaded.append(("unload", filename)),
        load_file=lambda filename: loaded.append(("load", filename)))
    monkeypatch.setitem(sys.modules, "kivy.lang", types.SimpleNamespace(Builder=fake_builder))
    reloader = dhr.DevHotReloader(str(isolated_source))
    assert reloader.reload_kv(os.path.join("ui", "kv", "search_screen.kv")) == \
        {"ui.screens.search_screen"}
    assert [action for action, _ in loaded] == ["unload", "load"]


# --------------------------------------------------------------------------- #
# desktop watcher                                                              #
# --------------------------------------------------------------------------- #

def test_watcher_classify_needs_restart():
    buckets = watcher.classify_changes(["main.py"])
    assert buckets["needs_restart"] is True
    assert watcher.classify_changes(["assets/next.png"])["needs_restart"] is True
    assert watcher.classify_changes(["ui/kv/a.kv", "ui/b.py"])["needs_restart"] is False


def test_watcher_pushes_and_removes_flat_pyc():
    cmds = watcher.build_push_commands(
        "adb", None, "io.github.fector101.melo",
        "/local/ui/screens/search_screen.py",
        os.path.join("ui", "screens", "search_screen.py"))
    assert cmds[0] == ["adb", "push", "/local/ui/screens/search_screen.py",
                       watcher.TMP_PUSH_NAME]
    assert cmds[2][-1] == \
        "/data/data/io.github.fector101.melo/files/app/ui/screens/search_screen.py"
    assert ["/data/data/io.github.fector101.melo/files/app/ui/screens/search_screen.pyc"
            in cmd for cmd in cmds].count(True) == 1
    assert any("__pycache__/search_screen.pyc" in " ".join(cmd) for cmd in cmds)
    assert watcher.pyc_paths("ui/screens/__init__.py") == [
        os.path.join("ui", "screens", "__init__.pyc"),
        os.path.join("ui", "screens", "__pycache__", "__init__.pyc")]


def test_watcher_injects_hook_before_melo_entry_point(tmp_path, monkeypatch):
    source = tmp_path / "app_src"
    source.mkdir()
    main = source / "main.py"
    main.write_text('class MeloApp:\n    pass\n\n'
                    'if __name__ == "__main__":\n    MeloApp().run()\n')
    args = watcher.parse_args(["--source", str(source), "--adb", "/bin/true",
                               "--dry-run"])
    w = watcher.HotReloadWatcher(args)
    # No main.py on the device yet -> fall back to the local clean source.
    monkeypatch.setattr(watcher.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(
                            returncode=1, stdout="", stderr=""))
    captured = []

    def fake_push(local, rel):
        captured.append((Path(local).read_text(), rel))
        return True

    monkeypatch.setattr(w, "push_local_file", fake_push)
    assert w.inject_main_hook() is True
    assert captured[0][1] == "main.py"
    hook, entry = captured[0][0].split('if __name__ == "__main__":', 1)
    assert "from utils.dev_hot_reload import maybe_start_dev_hot_reload" in hook
    assert "MeloApp().run()" in entry


def test_watcher_build_restart_commands():
    cmds = watcher.build_restart_commands(
        "adb", "SER1", "io.github.fector101.melo", "org.kivy.android.PythonActivity")
    assert cmds[0] == ["adb", "-s", "SER1", "shell", "am", "force-stop",
                       "io.github.fector101.melo"]
    assert cmds[2][:6] == ["adb", "-s", "SER1", "shell", "am", "start"]


def test_watcher_collect_changes_debounces(tmp_path):
    _touch(tmp_path, "ui/kv/a.kv")
    args = watcher.parse_args(["--source", str(tmp_path), "--adb", "/bin/true",
                               "--poll", "0.05", "--debounce", "0.15"])
    w = watcher.HotReloadWatcher(args)
    _touch(tmp_path, "ui/kv/a.kv", "changed")
    deadline = time.time() + 3
    batch = None
    while time.time() < deadline:
        batch = w.collect_changes()
        if batch:
            break
        time.sleep(0.05)
    assert batch == ["ui/kv/a.kv"]
    assert w.collect_changes() is None


def test_watcher_process_kv_only_does_not_restart(tmp_path):
    _touch(tmp_path, "ui/kv/a.kv")
    args = watcher.parse_args(["--source", str(tmp_path), "--adb", "/bin/true",
                               "--dry-run"])
    w = watcher.HotReloadWatcher(args)
    restarts = []
    w.restart = lambda: restarts.append(True)
    w.process(["ui/kv/a.kv"])
    assert restarts == []


def test_watcher_process_asset_triggers_restart(tmp_path):
    _touch(tmp_path, "assets/next.png")
    args = watcher.parse_args(["--source", str(tmp_path), "--adb", "/bin/true",
                               "--dry-run"])
    w = watcher.HotReloadWatcher(args)
    restarts = []
    w.restart = lambda: restarts.append(True)
    w.process(["assets/next.png"])
    assert restarts == [True]


def test_watcher_process_restart_mode_always_restarts(tmp_path):
    _touch(tmp_path, "ui/screens/search_screen.py")
    args = watcher.parse_args(["--source", str(tmp_path), "--adb", "/bin/true",
                               "--dry-run", "--mode", "restart"])
    w = watcher.HotReloadWatcher(args)
    restarts = []
    w.restart = lambda: restarts.append(True)
    w.process(["ui/screens/search_screen.py"])
    assert restarts == [True]
