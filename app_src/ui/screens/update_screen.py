"""The update screen.

The module is imported only after the update check has found a newer release.
It loads its KV file itself, so ``ui.load_kv_files()`` (and startup) never sees
or parses the update UI.
"""

import logging
import webbrowser

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import (AliasProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.utils import platform

from ui import load_kv
from ui import theme as THEME
from ui.widgets.update import AVATAR_TINTS, UpdateAvatar

logger = logging.getLogger("melo.update")


def _open_external(url):
    """Open a URL in the browser (the Android intent needs NEW_TASK)."""
    if not url:
        return
    try:
        if platform == "android":
            from jnius import autoclass
            from android import mActivity  # type: ignore

            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            mActivity.startActivity(intent)
        else:
            webbrowser.open(url)
    except Exception:
        logger.exception("Could not open %s", url)


class UpdateContent(BoxLayout):
    """The contents of the update screen."""

    version = StringProperty("")
    released = StringProperty("")
    installed = StringProperty("")
    size_text = StringProperty("")
    downloads = NumericProperty(0)
    last_updated = StringProperty("")
    repo = StringProperty("")
    apk_type = StringProperty("")
    release_url = StringProperty("")
    contributors = ListProperty([])
    highlights = ListProperty([])
    failure_text = StringProperty("")

    #: available -> downloading -> ready | failed; installing while the
    #: system installer is being opened.
    state = StringProperty("available")
    progress = NumericProperty(0)
    shown = NumericProperty(0)

    __events__ = ("on_back", "on_download", "on_cancel", "on_later",
                  "on_install", "on_open_release")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(highlights=self._fill_highlights,
                  contributors=self._fill_avatars)
        Clock.schedule_once(self._fill_highlights)
        Clock.schedule_once(self._fill_avatars)

    # ------------------------------------------------------------------ #
    # Derived text                                                        #
    # ------------------------------------------------------------------ #
    def _get_contributors_text(self):
        return "  \u00b7  ".join("@" + contributor
                                 for contributor in self.contributors)

    contributors_text = AliasProperty(
        _get_contributors_text, bind=["contributors"])

    def _get_contributors_count_text(self):
        count = len(self.contributors)
        return "%d contributor%s" % (count, "" if count == 1 else "s")

    contributors_count_text = AliasProperty(
        _get_contributors_count_text, bind=["contributors"])

    def _get_status_text(self):
        if self.state == "downloading":
            return "Downloading\u2026  %d%%" % self.progress
        if self.state == "ready":
            return "Download complete."
        if self.state == "installing":
            return "Opening installer\u2026"
        if self.state == "failed":
            return (self.failure_text
                    or "Download failed. Check your connection and retry.")
        return "Securely sourced from GitHub."

    status_text = AliasProperty(
        _get_status_text, bind=["state", "progress", "failure_text"])

    def _get_primary_text(self):
        return {
            "available": "Download update",
            "idle": "Download update",
            "downloading": "Downloading\u2026",
            "ready": "Install",
            "installing": "Installing\u2026",
            "failed": "Retry",
        }.get(self.state, "Download update")

    primary_text = AliasProperty(_get_primary_text, bind=["state"])

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #
    def _fill_highlights(self, *_):
        box = self.ids.get("highlights")
        if box is None:
            return
        box.clear_widgets()
        for text in self.highlights:
            label = Label(
                text="\u2022   " + text,
                font_size="14sp",
                color=THEME.UPDATE_HIGHLIGHT,
                halign="left",
                valign="top",
                size_hint_y=None,
            )
            label.bind(width=lambda lbl, width: setattr(
                lbl, "text_size", (width, None)))
            label.bind(texture_size=lambda lbl, texture: setattr(
                lbl, "height", texture[1]))
            box.add_widget(label)

    def _fill_avatars(self, *_):
        box = self.ids.get("avatars")
        if box is None:
            return
        box.clear_widgets()
        names = self.contributors[:3]
        step = dp(20)
        box.width = dp(26) + step * max(len(names) - 1, 0)
        for index, name in enumerate(names):
            box.add_widget(UpdateAvatar(
                letter=str(name)[:1].upper(),
                tint=AVATAR_TINTS[index % len(AVATAR_TINTS)],
                pos=(index * step, dp(9)),
            ))

    def set_progress(self, value):
        self.progress = max(0, min(100, value))
        Animation.cancel_all(self, "shown")
        Animation(shown=self.progress, d=0.15).start(self)

    # ------------------------------------------------------------------ #
    # Buttons                                                             #
    # ------------------------------------------------------------------ #
    def primary_pressed(self):
        if self.state in ("available", "idle", "failed"):
            self.dispatch("on_download")
        elif self.state == "ready":
            self.dispatch("on_install")

    def secondary_pressed(self):
        if self.state == "downloading":
            self.dispatch("on_cancel")
        else:
            self.dispatch("on_later")

    # ------------------------------------------------------------------ #
    # Default event handlers (the screen binds the real ones)             #
    # ------------------------------------------------------------------ #
    def on_back(self):
        pass

    def on_download(self):
        pass

    def on_cancel(self):
        pass

    def on_later(self):
        pass

    def on_install(self):
        pass

    def on_open_release(self):
        _open_external(self.release_url)


class UpdateScreen(Screen):
    """A full-window update screen driven by an :class:`UpdateViewModel`."""

    def __init__(self, view_model, **kwargs):
        super().__init__(**kwargs)

        self.name = "update"
        self.view_model = view_model
        self.size_hint = (1, 1)

        content = self.content
        content.bind(on_back=self.on_back,
                     on_download=self._on_download,
                     on_cancel=self._on_cancel,
                     on_later=self._on_later,
                     on_install=self._on_install)
        self._bind_view_model()
        self.view_model.load_details()

    @property
    def content(self):
        """The ``UpdateContent`` the KV rule created for this screen."""
        return self.ids.main_container

    def _bind_view_model(self):
        vm = self.view_model
        content = self.content
        content.version = vm.version
        content.released = vm.released
        content.installed = vm.installed
        content.size_text = vm.size_text
        content.downloads = vm.downloads
        content.last_updated = vm.last_updated
        content.repo = vm.repo
        content.apk_type = vm.apk_type
        content.release_url = vm.release_url
        content.highlights = vm.highlights
        content.contributors = vm.contributors
        content.failure_text = vm.failure_text
        content.state = vm.state
        content.set_progress(vm.progress)

        vm.bind(state=content.setter("state"),
                progress=lambda _vm, value: content.set_progress(value),
                contributors=content.setter("contributors"),
                failure_text=content.setter("failure_text"))

    def apply_padding(self, inset_top, inset_bottom):
        """Keep the layout clear of the system bars (Android 15+ edge-to-edge)."""
        self.ids.main_container.padding = [
            dp(19), inset_top + dp(8), dp(19), inset_bottom + dp(10)]

    # ------------------------------------------------------------------ #
    # Android back / desktop Escape                                       #
    # ------------------------------------------------------------------ #
    def on_enter(self):
        Window.bind(on_keyboard=self._on_window_key)

    def on_leave(self):
        Window.unbind(on_keyboard=self._on_window_key)

    def _on_window_key(self, _window, key, *_):
        if key == 27:
            self.on_back()
            return True
        return False

    # ------------------------------------------------------------------ #
    # Commands from the content                                           #
    # ------------------------------------------------------------------ #
    def on_back(self, *_):
        """Cancel a running download and return to the library."""
        if self.view_model.state == "downloading":
            self.view_model.cancel()
        self._return_to_library()

    def _return_to_library(self):
        manager = self.manager
        if manager is None:
            return
        library_screen = manager.get_screen("library") if manager.has_screen("library") else None
        if library_screen is not None:
            library_screen.show_update_chip(self.view_model.version)
        manager.current = "library"

    def _on_later(self, *_):
        self.on_back()

    def _on_download(self, *_):
        self.view_model.download()

    def _on_cancel(self, *_):
        self.view_model.cancel()

    def _on_install(self, *_):
        self.view_model.install()


load_kv("update_screen.kv")
