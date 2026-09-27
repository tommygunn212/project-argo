"""The air-conditioner voice tools in core/realtime_tools/home.py.

core.smart_home is stubbed: these pin what the model is told, not the SDK.
"""

from dataclasses import dataclass

import pytest

from core import smart_home
from core import realtime_tools as T


@dataclass
class FakeUnit:
    name: str = "Bedroom"
    power: bool = True
    raw: dict = None

    def describe(self) -> str:
        return f"{self.name} is {'on' if self.power else 'off'}"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(smart_home, "credentials_present", lambda: True)


def test_unconfigured_says_how_to_configure(monkeypatch):
    monkeypatch.setattr(smart_home, "credentials_present", lambda: False)
    d = T.ac_list()
    assert d["ok"] is False and d["error"] == "not_configured" and ".env" in d["message"]


def test_status_hides_the_raw_sdk_payload(configured, monkeypatch):
    monkeypatch.setattr(smart_home, "ac_state", lambda name: FakeUnit(raw={"secret": 1}))
    d = T.ac_status("bedroom")
    assert d["ok"] and d["description"] == "Bedroom is on" and "raw" not in d


def test_sdk_refusal_is_spoken_not_raised(configured, monkeypatch):
    def refuse(name, **kwargs):
        raise smart_home.SmartHomeError("Target temperature must be between 60 and 86 degrees")

    monkeypatch.setattr(smart_home, "ac_set", refuse)
    d = T.ac_control("bedroom", temperature_f=99)
    assert d["ok"] is False and d["error"] == "smart_home_error" and "60 and 86" in d["message"]


def test_only_what_was_asked_is_changed(configured, monkeypatch):
    seen = {}
    monkeypatch.setattr(smart_home, "ac_set", lambda name, **kw: seen.update(kw) or FakeUnit())
    assert T.ac_control("bedroom", power="Off")["ok"]
    assert seen == {"power": False, "temperature_f": None, "mode": None, "fan": None}


def test_an_unrecognised_power_word_is_refused_not_ignored(configured, monkeypatch):
    """It used to become power=None - no change - and still report ok."""
    monkeypatch.setattr(smart_home, "ac_set", lambda *a, **k: pytest.fail("must not be called"))
    d = T.ac_control("bedroom", power="max")
    assert d["ok"] is False and d["error"] == "unknown_power"
