"""The UI layer: widgets, screens and the KV rules that style them.

Nothing below this package knows about the repositories; the screens talk to
the view models only.
"""

import os

from kivy.lang import Builder

#: The directory with the KV rules of this layer.
KV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kv")


def load_kv_files():
    """Load every ``.kv`` file of the UI layer.

    The paths are absolute: on Android the working directory is not the app
    directory, so a relative path would not resolve.
    """
    for name in sorted(os.listdir(KV_DIR)):
        if name.endswith(".kv"):
            Builder.load_file(os.path.join(KV_DIR, name))
