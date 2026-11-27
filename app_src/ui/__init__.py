"""The UI layer: widgets, screens and the KV rules that style them.

Nothing below this package knows about the repositories; the screens talk to
the view models only.
"""

import os

from kivy.lang import Builder

#: The widget rules, loaded at startup.
KV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kv", "widgets")

#: The screen rules; every screen loads its own when it is first navigated to.
SCREENS_KV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kv")


def load_kv_files():
    """Load every widget ``.kv`` file of the UI layer (not the screens')."""
    for name in sorted(os.listdir(KV_DIR)):
        if name.endswith(".kv"):
            Builder.load_file(os.path.join(KV_DIR, name))


def load_kv(*name):
    """Loads any kv file
    Accepts a list of folders and a file path
    """
    Builder.load_file(os.path.join(SCREENS_KV_DIR, *name))
