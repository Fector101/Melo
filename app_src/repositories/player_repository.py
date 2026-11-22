"""Shared playlist state for the player.

Screens set ``current_playlist`` (the library or the current search results);
``PlayerViewModel`` reads it. Keeping it here lets navigation between library
and search reuse the one player
"""

# This class is new and was created to combat current playlist issue, but in the future more of PlayerViewModel data will be routed from here
# current_playlist can be changed from any screen then player vm just only reads in repo class
class PlayerRepository:
    """The playlist the single app-wide player walks through."""

    def __init__(self):
        self.current_playlist = []

    # #: The track that is loaded (None when nothing is loaded).
    # current_track = ObjectProperty(None, allownone=True)
    #