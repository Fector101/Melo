"""Holds data the player uses to songs"""
from kivy.properties import ListProperty, ObjectProperty


class PlayerRepository:

    # this value will get routed to player viewmodel :(
    current_playlist = []

    # #: The track that is loaded (None when nothing is loaded).
    # current_track = ObjectProperty(None, allownone=True)
    #
    #