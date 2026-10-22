"""Android system-bar insets.

Android 15 (targetSdk 35+) enforces edge-to-edge: the window always draws
behind the status bar and the nav buttons, and no manifest option can reserve
space for them - buildozer's ``android.display_cutout`` only concerns the notch
and is overridden to ``always`` by the system anyway (verified via dumpsys).
So the root widget pads itself with the real window insets instead, refreshed
whenever the system reports a change (e.g. 3-button <-> gesture navigation).

Off Android every helper is a no-op and the insets stay at 0.
"""

import logging

from android_notify.config import (get_python_activity_context,
                                   on_android_platform)
from kivy.clock import Clock
from core.android_bridge import PythonJavaClass, autoclass, java_method

logger = logging.getLogger("melo.insets")

# JNI objects are held at module level so the GC leaves them alone for the
# lifetime of the process.
_insets_listener = None
_insets_register = None


def read_insets(insets):
    """WindowInsets -> status/nav/cutout insets in **physical pixels**.

    Kivy lays out in pixels on Android, so the raw values slot straight into
    KV positions/sizes. ``getInsetsIgnoringVisibility`` keeps the padding
    stable while a bar is temporarily hidden (immersive swipe, keyboard).
    """
    if autoclass("android.os.Build$VERSION").SDK_INT >= 30:
        inset_type = autoclass("android.view.WindowInsets$Type")
        bars = inset_type.statusBars() | inset_type.navigationBars()
        system = insets.getInsetsIgnoringVisibility(bars)
        top, bottom = system.top, system.bottom
        left, right = system.left, system.right
    else:  # API 28/29: WindowInsets.Type does not exist yet
        top = insets.getSystemWindowInsetTop()
        bottom = insets.getSystemWindowInsetBottom()
        left = insets.getSystemWindowInsetLeft()
        right = insets.getSystemWindowInsetRight()
    try:
        cutout = insets.getDisplayCutout()  # API 28+; None when there is none
        if cutout is not None:
            top = max(top, cutout.getSafeInsetTop())
            bottom = max(bottom, cutout.getSafeInsetBottom())
            left = max(left, cutout.getSafeInsetLeft())
            right = max(right, cutout.getSafeInsetRight())
    except Exception as error:
        logger.debug("no display-cutout insets: %s", error)
    return {"top": top, "bottom": bottom, "left": left, "right": right}


def _resource_inset_px(dimen_name):
    """Fallback px inset from an Android resource (before the callback fires)."""
    try:
        resources = get_python_activity_context().getResources()
        res_id = resources.getIdentifier(dimen_name, "dimen", "android")
        return int(resources.getDimensionPixelSize(res_id)) if res_id else 0
    except Exception as error:
        logger.debug("%s resource unavailable: %s", dimen_name, error)
        return 0


def _fallback_insets():
    return {"top": _resource_inset_px("status_bar_height"),
            "bottom": _resource_inset_px("navigation_bar_height"),
            "left": 0, "right": 0}


def _apply_insets(root, insets):
    """Push insets onto the Kivy root from whichever thread reported them."""

    def _set(_dt):
        root.inset_top = insets["top"]
        root.inset_bottom = insets["bottom"]
        root.inset_left = insets["left"]
        root.inset_right = insets["right"]

    # Kivy properties change on Kivy's own thread
    Clock.schedule_once(_set, 0)


if on_android_platform() and PythonJavaClass is not None:

    class _InsetsListener(PythonJavaClass):
        __javainterfaces__ = ["android/view/View$OnApplyWindowInsetsListener"]
        __javacontext__ = "app"

        def __init__(self, apply_insets):
            super().__init__()
            self._apply_insets = apply_insets

        @java_method("(Landroid/view/View;Landroid/view/WindowInsets;)"
                     "Landroid/view/WindowInsets;")
        def onApplyWindowInsets(self, view, insets):
            try:
                self._apply_insets(read_insets(insets))
            except Exception as error:
                logger.warning("window-insets callback failed: %s", error)
            return insets  # un-consumed: SDL's own listener must keep seeing them

    class _RegisterInsetsRunnable(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        def __init__(self, decor, listener):
            super().__init__()
            self._decor = decor
            self._listener = listener

        @java_method("()V")
        def run(self):
            # Set on the decor view: SDL listens on SDLSurface instead, so the
            # two listeners do not overwrite each other.
            self._decor.setOnApplyWindowInsetsListener(self._listener)
            self._decor.requestApplyInsets()


def attach_insets(root):
    """Keep ``root``'s inset properties in sync with the real system bars.

    No-op off Android. Falls back to Android's dimension resources so the
    layout never starts out overlapping the bars if the callback is delayed;
    the callback then corrects the values as soon as the view is attached.
    """
    global _insets_listener, _insets_register

    if not on_android_platform():
        return
    try:
        activity = get_python_activity_context()
        decor = activity.getWindow().getDecorView()

        listener = _InsetsListener(lambda insets: _apply_insets(root, insets))
        register = _RegisterInsetsRunnable(decor, listener)
        _insets_listener, _insets_register = listener, register
        activity.runOnUiThread(register)

        current = decor.getRootWindowInsets()
        if current is not None:
            _apply_insets(root, read_insets(current))
        else:  # not attached yet: requestApplyInsets() above follows up
            _apply_insets(root, _fallback_insets())
    except Exception as error:
        logger.warning("system-bar inset setup failed: %s", error)
        _apply_insets(root, _fallback_insets())
