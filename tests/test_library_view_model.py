"""The library view model: the scan flow and the cover art."""

import pytest

from conftest import wait_for
from models.track import Track
from viewmodels.library_view_model import LibraryViewModel


@pytest.fixture
def library_vm(library, artwork, permissions):
    return LibraryViewModel(library, artwork, permissions)


def make_tracks(count=2):
    return [Track(path=f"/music/{index}.mp3", title=f"Track {index}",
                  artist=f"Artist {index}", duration_ms=30000)
            for index in range(count)]


# --------------------------------------------------------------------------- #
# The scan                                                                    #
# --------------------------------------------------------------------------- #
def test_scanning_off_android_says_so(library_vm):
    library_vm.scan()

    assert library_vm.status_text == "Scanning needs Android (device example)"
    assert library_vm.tracks == []


def test_a_missing_manifest_permission_is_explained(library_vm, on_android,
                                                     permissions):
    permissions.declared = False

    library_vm.scan()

    assert "READ_MEDIA_AUDIO" in library_vm.status_text
    assert library_vm.tracks == []


def test_the_scan_asks_for_the_permission_first(library_vm, on_android,
                                                permissions, immediate_clock):
    permissions.granted = False

    library_vm.scan()

    assert permissions.requested is True
    assert library_vm.status_text == "Audio access denied"


def test_the_scan_loads_the_tracks(library_vm, on_android, permissions,
                                   library, immediate_clock):
    permissions.granted = True
    library.tracks = make_tracks()

    library_vm.scan()

    assert wait_for(lambda: library_vm.tracks)
    assert [track.path for track in library_vm.tracks] == ["/music/0.mp3",
                                                           "/music/1.mp3"]
    assert library_vm.status_text == "2 songs added"
    assert library_vm.is_scanning is False


def test_an_empty_library_is_reported(library_vm, on_android, permissions,
                                      immediate_clock):
    permissions.granted = True

    library_vm.scan()

    assert wait_for(lambda: "No loadable file paths" in library_vm.status_text)
    assert library_vm.tracks == []


# --------------------------------------------------------------------------- #
# The cover art                                                               #
# --------------------------------------------------------------------------- #
def test_the_artwork_is_announced(library_vm, artwork, immediate_clock):
    artwork.art["/music/0.mp3"] = "/cache/0.jpg"
    library_vm.tracks = make_tracks()
    seen = []
    library_vm.bind(on_artwork_ready=lambda _vm, **kwargs: seen.append(kwargs))

    library_vm.load_artwork()

    assert wait_for(lambda: seen)
    assert seen == [{"path": "/music/0.mp3", "art": "/cache/0.jpg"}]


def test_the_cached_artwork_is_answered_without_io(library_vm, artwork):
    artwork.art["/music/0.mp3"] = "/cache/0.jpg"

    assert library_vm.cached_artwork("/music/0.mp3") == "/cache/0.jpg"
    assert library_vm.cached_artwork("/music/1.mp3") == ""


def test_a_track_is_found_by_its_path(library_vm):
    tracks = make_tracks()
    library_vm.tracks = tracks

    assert library_vm.track_by_path("/music/1.mp3") is tracks[1]
    assert library_vm.track_by_path("/music/nope.mp3") is None
