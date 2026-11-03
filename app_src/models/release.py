"""The release metadata the updater works with.

A release is described by GitHub's ``/releases/latest`` payload, but only the
parts Melo needs are kept here. The model stays free of Kivy and of network
code so it can be tested on its own.
"""

import re
from dataclasses import dataclass

#: The owner/repository the updater reads releases from.
DEFAULT_REPO = "Fector101/Melo"

#: What the update screen shows when a release has no readable notes.
DEFAULT_HIGHLIGHTS = (
    "Performance improvements.",
    "Bug fixes.",
    "UI refinements.",
)

_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.+)$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKUP = re.compile(r"[*_`~]+")


def _clean_markdown(value):
    """Turn one line of release-note markdown into plain display text."""
    value = _LINK.sub(r"\1", value)
    value = _MARKUP.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -")


def parse_highlights(text, limit=6):
    """Return up to ``limit`` short highlight lines from a release note.

    The version notes are markdown. Bullets are the common form; when a body
    has no bullets the first prose lines are used, and the built-in defaults
    are the last resort.
    """
    highlights = []
    for line in (text or "").splitlines():
        match = _BULLET.match(line)
        if match is None:
            continue
        cleaned = _clean_markdown(match.group(1))
        if cleaned:
            highlights.append(cleaned)
        if len(highlights) >= limit:
            return highlights
    if highlights:
        return highlights

    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">", "|")):
            continue
        cleaned = _clean_markdown(stripped)
        if not cleaned or cleaned.lower().startswith(("thanks", "thank you")):
            continue
        highlights.append(cleaned)
        if len(highlights) >= limit:
            break
    return highlights or list(DEFAULT_HIGHLIGHTS)


@dataclass(frozen=True)
class ReleaseAsset:
    """The APK asset selected for this device."""

    name: str
    size: int
    download_url: str
    abi: str | None = None
    downloads: int = 0
    updated_at: str = ""


@dataclass(frozen=True)
class Release:
    """A newer GitHub release that Melo can offer."""

    version: str
    tag: str
    notes: str
    body: str
    html_url: str
    published_at: str
    asset: ReleaseAsset
    repo: str = DEFAULT_REPO
