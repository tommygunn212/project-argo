"""Opening apps and asking for an era must actually work.

ARGO's curated app registry knows five apps, so "open Photoshop" resolved to
None and did nothing. And the track database stores a year that query_tracks
already accepts, but nothing exposed it, so an era could not be asked for.
"""

import pytest

from core import app_resolver as R
from core import realtime_tools as T


# --- era parsing -----------------------------------------------------------

@pytest.mark.parametrize("said,expected", [
    ("80s", (1980, 1989)),
    ("the 80s", (1980, 1989)),
    ("1980s", (1980, 1989)),
    ("'80s", (1980, 1989)),
    ("eighties", (1980, 1989)),
    ("the seventies", (1970, 1979)),
    ("nineties", (1990, 1999)),
    ("1975", (1975, 1975)),
    ("1975 to 1980", (1975, 1980)),
    ("1975-1980", (1975, 1980)),
    ("2000s", (2000, 2009)),
    ("60s", (1960, 1969)),
])
def test_era_parses(said, expected):
    assert T.parse_era(said) == expected


@pytest.mark.parametrize("said", ["", "   ", "disco era", "something old"])
def test_unparseable_era_is_reported_not_guessed(said):
    assert T.parse_era(said) is None


def test_unparseable_era_returns_a_clear_failure():
    d = T.music_play_era("whenever")
    assert d["ok"] is False and d["error"] == "unparsed_era"


def test_two_digit_decade_disambiguates_to_this_century():
    assert T.parse_era("20s") == (2020, 2029)


# --- the library actually has these years ---------------------------------

@pytest.mark.parametrize("decade", [1960, 1970, 1980, 1990, 2000])
def test_library_has_tracks_for_each_decade(decade):
    from core.music_player import MusicDatabase

    rows = MusicDatabase().query_tracks(year_start=decade, year_end=decade + 9, limit=5)
    assert rows, f"no tracks indexed for the {decade}s"


def test_era_query_returns_playable_paths():
    from core.music_player import MusicDatabase

    rows = MusicDatabase().query_tracks(year_start=1980, year_end=1989, limit=5) or []
    assert rows
    assert rows[0].get("path"), "tracks must carry a path to be playable"
    assert "song" in rows[0], "the track name key is 'song'; don't read 'title'"


# --- app resolution --------------------------------------------------------

def test_curated_registry_still_wins():
    hit = R.resolve("notepad")
    assert hit and hit["source"] == "argo_registry"


def test_resolves_apps_outside_the_curated_five():
    """The regression: these all returned None and the open silently did nothing."""
    missed = [name for name in ("photoshop", "premiere", "vs code", "obs")
              if R.resolve(name) is None]
    assert not missed, f"still unresolvable: {missed}"


def test_taskbar_pins_are_a_resolution_source():
    pins = R._taskbar_index()
    assert pins, "no taskbar pins found"
    any_pin = next(iter(pins.values())).stem
    assert R.resolve(any_pin) is not None


def test_unknown_app_is_reported_not_invented():
    assert R.resolve("definitely not installed xyzzy") is None
    d = T.app_open("definitely not installed xyzzy")
    assert d["ok"] is False and d["error"] == "not_installed"


def test_launchable_list_is_substantial_and_names_the_pins():
    d = T.apps_launchable()
    assert d["ok"]
    assert d["count"] > 50, "resolution should cover installed software, not a handful"
    assert d["pinned"], "taskbar pins should be reported separately"
