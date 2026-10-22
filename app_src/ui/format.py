"""Formatting helpers for the UI layer."""


def format_duration(seconds):
    """``125`` -> ``'2:05'``."""
    seconds = int(max(0, seconds or 0))
    # return f"{seconds // 60}:{seconds % 60:02d}"
    t=f"{seconds // 60}:{seconds % 60:02d}"
    h=seconds//(60*60)
    t = f"{h}:{t}" if h else t
    return t
