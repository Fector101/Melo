"""The repository layer: everything that touches the device.

Repositories are the only place that talks to Android (MediaStore, the audio
engine, the media notification). They return plain data and never import
anything from the UI layer.
"""
