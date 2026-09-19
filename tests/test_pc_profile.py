"""core.pc_profile: the gaming/editing power-plan + display + app-close switch.

Everything that would actually touch the machine (powercfg, ChangeDisplaySettingsW,
closing apps) is monkeypatched here - these tests pin the composition and the
verify-after-write contract, not the real Windows calls, which is what
tests/test_app_control.py already does for subprocess-based tool bodies.
"""

import json

import pytest

from core import pc_profile as P


# --- plan name resolution ---------------------------------------------------

def test_resolve_known_plan_names_to_builtin_guids():
    assert P._resolve_plan_guid("high_performance") == P.BUILTIN_POWER_PLANS["high_performance"]
    assert P._resolve_plan_guid("Balanced") == P.BUILTIN_POWER_PLANS["balanced"]
    assert P._resolve_plan_guid("power saver") == P.BUILTIN_POWER_PLANS["power_saver"]


def test_resolve_unknown_string_passes_through_as_literal_guid():
    literal = "11111111-2222-3333-4444-555555555555"
    assert P._resolve_plan_guid(literal) == literal


# --- set_power_plan verifies from disk, never trusts the write -------------

def test_set_power_plan_verifies_against_active_scheme(monkeypatch):
    calls = []

    def fake_run_powercfg(*args):
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(P, "_run_powercfg", fake_run_powercfg)
    monkeypatch.setattr(
        P, "get_active_power_plan",
        lambda: {"ok": True, "guid": P.BUILTIN_POWER_PLANS["high_performance"], "name": "High performance"},
    )

    result = P.set_power_plan("high_performance")

    assert result["ok"] is True
    assert calls == [("/setactive", P.BUILTIN_POWER_PLANS["high_performance"])]


def test_set_power_plan_reports_unverified_when_active_scheme_disagrees(monkeypatch):
    monkeypatch.setattr(P, "_run_powercfg", lambda *a: (True, "ok"))
    monkeypatch.setattr(
        P, "get_active_power_plan",
        lambda: {"ok": True, "guid": P.BUILTIN_POWER_PLANS["balanced"], "name": "Balanced"},
    )

    result = P.set_power_plan("high_performance")

    assert result["ok"] is False  # setactive claimed success but the scheme didn't change


def test_set_power_plan_duplicates_ultimate_performance_first(monkeypatch):
    calls = []
    monkeypatch.setattr(P, "_run_powercfg", lambda *a: calls.append(a) or (True, "ok"))
    monkeypatch.setattr(
        P, "get_active_power_plan",
        lambda: {"ok": True, "guid": P.BUILTIN_POWER_PLANS["ultimate_performance"], "name": "Ultimate"},
    )

    P.set_power_plan("ultimate_performance")

    assert calls[0] == ("/duplicatescheme", P.BUILTIN_POWER_PLANS["ultimate_performance"])
    assert calls[1] == ("/setactive", P.BUILTIN_POWER_PLANS["ultimate_performance"])


# --- apply_profile: mode validation and composition -------------------------

def test_apply_profile_rejects_unknown_mode():
    result = P.apply_profile("turbo")
    assert result["ok"] is False
    assert result["error"] == "bad_mode"


def test_apply_profile_composes_plan_display_and_app_close(monkeypatch, tmp_path):
    cfg = {
        "pc_profiles": {
            "gaming": {"power_plan": "high_performance", "refresh_hz": 144, "close_apps": ["chrome"]},
            "editing": {"power_plan": "balanced", "refresh_hz": 60, "close_apps": []},
        }
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "STATE_PATH", tmp_path / "data" / "pc_profile_state.json")

    monkeypatch.setattr(P, "get_active_power_plan", lambda: {"ok": True, "guid": "before", "name": "Balanced"})
    monkeypatch.setattr(P, "get_display_settings", lambda: {"ok": True, "width": 1920, "height": 1080, "refresh_hz": 60})
    monkeypatch.setattr(P, "set_power_plan", lambda plan_ref: {"ok": True, "requested": plan_ref})
    monkeypatch.setattr(P, "set_refresh_rate", lambda hz: {"ok": True, "requested_hz": hz})
    monkeypatch.setattr(P, "_close_configured_apps", lambda names: [{"app": n, "ok": True} for n in names])

    result = P.apply_profile("gaming")

    assert result["ok"] is True
    assert result["power_plan"]["requested"] == "high_performance"
    assert result["display"]["requested_hz"] == 144
    assert result["closed_apps"] == [{"app": "chrome", "ok": True}]
    assert P._load_last_mode() == "gaming"


def test_apply_profile_skips_display_and_apps_when_not_configured(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "STATE_PATH", tmp_path / "data" / "pc_profile_state.json")

    monkeypatch.setattr(P, "get_active_power_plan", lambda: {"ok": True, "guid": "before"})
    monkeypatch.setattr(P, "get_display_settings", lambda: {"ok": True, "width": 1920, "height": 1080, "refresh_hz": 60})
    monkeypatch.setattr(P, "set_power_plan", lambda plan_ref: {"ok": True, "requested": plan_ref})

    def _boom(*a, **k):
        raise AssertionError("should not be called when refresh_hz is unset")

    monkeypatch.setattr(P, "set_refresh_rate", _boom)

    result = P.apply_profile("editing")  # DEFAULT_PROFILES: editing -> balanced, no refresh, no apps

    assert result["ok"] is True
    assert result["display"] is None
    assert result["closed_apps"] == []


def test_load_profiles_falls_back_to_defaults_on_malformed_config(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(P, "ROOT", tmp_path)

    assert P._load_profiles() == P.DEFAULT_PROFILES
