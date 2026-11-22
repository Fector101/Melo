"""Holds data the player uses to songs"""

# This class is new and was created to combat current playlist issue, but in the future more of PlayerViewModel data will be routed from here
# current_playlist can be changed from any screen then player vm just only reads in repo class
class PlayerRepository:

    # this value will get routed to player viewmodel :(
    current_playlist = []

    # #: The track that is loaded (None when nothing is loaded).
    # current_track = ObjectProperty(None, allownone=True)
    #
    #