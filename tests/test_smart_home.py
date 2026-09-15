"""Offline tests for the GE SmartHQ client.

None of these touch the network. The point is to prove the things that would
hurt if they were wrong: that credentials never leak, that a spoken word maps to
the right enum, that a bad temperature is refused before it reaches the unit,
and that name matching finds the right air conditioner.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import smart_home as sh  # noqa: E402


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

def test_redact_removes_a_known_secret():
    sh._remember_secret("sup3r-secret-pw")
    assert "sup3r-secret-pw" not in sh.redact("login failed for sup3r-secret-pw")
    assert "<redacted>" in sh.redact("login failed for sup3r-secret-pw")


def test_redact_scrubs_bearer_tokens_it_has_never_seen():
    token = "redaction-test-token"
    out = sh.redact(f"Authorization: Bearer {token}")
    assert token not in out


def test_redact_leaves_ordinary_text_alone():
    assert sh.redact("bedroom ac is set to 72") == "bedroom ac is set to 72"


def test_short_values_are_not_registered_as_secrets():
    """A 3-character password would otherwise scrub half of every message."""
    before = set(sh._SECRETS)
    sh._remember_secret("on")
    assert set(sh._SECRETS) == before


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------

def test_credential_status_never_exposes_the_password(monkeypatch):
    monkeypatch.setenv(sh.ENV_USER, "tommy@example.com")
    monkeypatch.setenv(sh.ENV_PASS, "a-real-password")
    status = sh.credential_status()
    assert status["configured"] is True
    assert "a-real-password" not in str(status)
    assert "tommy@example.com" not in str(status)


def test_missing_credentials_raise_a_clear_error(monkeypatch):
    monkeypatch.delenv(sh.ENV_USER, raising=False)
    monkeypatch.delenv(sh.ENV_PASS, raising=False)
    monkeypatch.setattr(sh, "_dotenv_lookup", lambda name: None)
    assert sh.credentials_present() is False
    with pytest.raises(sh.SmartHomeError) as exc:
        sh._resolve_credentials()
    assert sh.ENV_USER in str(exc.value)


def test_environment_beats_dotenv(monkeypatch):
    monkeypatch.setenv(sh.ENV_USER, "from-env")
    monkeypatch.setattr(sh, "_dotenv_lookup", lambda name: "from-dotenv")
    assert sh._env(sh.ENV_USER) == "from-env"


def test_dotenv_is_used_when_environment_is_empty(monkeypatch):
    monkeypatch.delenv(sh.ENV_USER, raising=False)
    monkeypatch.setattr(sh, "_dotenv_lookup", lambda name: "from-dotenv")
    assert sh._env(sh.ENV_USER) == "from-dotenv"


def test_dotenv_strips_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('GE_SMARTHQ_USERNAME="quoted@example.com"\n', encoding="utf-8")
    monkeypatch.setattr(sh, "DOTENV", env)
    assert sh._dotenv_lookup(sh.ENV_USER) == "quoted@example.com"


def test_dotenv_ignores_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# GE_SMARTHQ_USERNAME=commented-out\n", encoding="utf-8")
    monkeypatch.setattr(sh, "DOTENV", env)
    assert sh._dotenv_lookup(sh.ENV_USER) is None


# --------------------------------------------------------------------------
# Spoken words to SDK enums
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("cool", "COOL"),
        ("COOL", "COOL"),
        ("heat", "HEAT"),
        ("auto", "AUTO"),
        ("dry", "DRY"),
        ("fan only", "FAN_ONLY"),
        ("fan_only", "FAN_ONLY"),
        ("energy saver", "ENERGY_SAVER"),
    ],
)
def test_spoken_mode_maps_to_the_right_enum(spoken, expected):
    assert sh._coerce_enum("ErdAcOperationMode", spoken).name == expected


@pytest.mark.parametrize("spoken,expected", [("low", "LOW"), ("high", "HIGH"), ("auto", "AUTO")])
def test_spoken_fan_speed_maps_to_the_right_enum(spoken, expected):
    assert sh._coerce_enum("ErdAcFanSetting", spoken).name == expected


def test_an_unknown_mode_lists_the_real_options():
    with pytest.raises(sh.SmartHomeError) as exc:
        sh._coerce_enum("ErdAcOperationMode", "arctic blast")
    assert "cool" in str(exc.value)


# --------------------------------------------------------------------------
# Guard rails
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [32, 59, 87, 120, -10])
def test_absurd_temperatures_are_refused(bad):
    import asyncio

    with pytest.raises(sh.SmartHomeError):
        asyncio.run(sh.async_ac_set("bedroom", temperature_f=bad))


@pytest.mark.parametrize("ok", [60, 68, 72, 86])
def test_sane_temperatures_pass_the_bounds_check(ok, monkeypatch):
    """The bound check must not be what rejects a reasonable request."""
    import asyncio

    async def fake(job, **kwargs):
        return "reached-transport"

    monkeypatch.setattr(sh, "_with_client", fake)
    assert asyncio.run(sh.async_ac_set("bedroom", temperature_f=ok)) == "reached-transport"


def test_air_handler_is_not_treated_as_a_room_unit():
    assert "AIR_HANDLER_VRF" not in sh.AC_TYPE_NAMES
    assert "SPLIT_AIR_CONDITIONER" in sh.AC_TYPE_NAMES


# --------------------------------------------------------------------------
# Matching a unit by what Tommy actually says
# --------------------------------------------------------------------------

class _Named:
    def __init__(self, name):
        self.name = name


def _names(items):
    return [i.name for i in items]


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("Bedroom ac", "Bedroom ac"),
        ("bedroom", "Bedroom ac"),
        ("BEDROOM AC", "Bedroom ac"),
        ("living room ac", "living room ac"),
        ("living", "living room ac"),
        ("livingroom", "living room ac"),
    ],
)
def test_matching_finds_the_unit_he_means(spoken, expected):
    units = [_Named("Bedroom ac"), _Named("living room ac")]
    found = sh._match(units, spoken, lambda u: u.name)
    assert found is not None and found.name == expected


def test_matching_returns_nothing_for_an_unknown_room():
    units = [_Named("Bedroom ac"), _Named("living room ac")]
    assert sh._match(units, "garage", lambda u: u.name) is None


def test_matching_an_empty_string_returns_nothing():
    assert sh._match([_Named("Bedroom ac")], "", lambda u: u.name) is None


# --------------------------------------------------------------------------
# Value decoding
# --------------------------------------------------------------------------

def test_on_off_decoding():
    class Erd:
        def __init__(self, name):
            self.name = name

    assert sh._as_bool(Erd("ON")) is True
    assert sh._as_bool(Erd("OFF")) is False
    assert sh._as_bool(None) is None
    assert sh._as_bool(True) is True


def test_temperature_decoding_handles_plain_numbers_and_wrappers():
    class Temp:
        fahrenheit = 72.0

    assert sh._as_number(Temp()) == 72.0
    assert sh._as_number(68) == 68.0
    assert sh._as_number(None) is None


def test_describe_is_speakable():
    unit = sh.AcUnit(name="Bedroom ac", mac="AA", appliance_type="AIR_CONDITIONER")
    assert "state unknown" in unit.describe()

    unit.power_on = False
    assert unit.describe() == "Bedroom ac - off"

    unit.power_on = True
    unit.ambient_f = 78.0
    unit.target_f = 72.0
    unit.mode = "COOL"
    spoken = unit.describe()
    assert "on" in spoken and "78" in spoken and "72" in spoken and "cool" in spoken
