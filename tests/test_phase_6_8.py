"""Phase 4-8 additions: printer ask-first flow, quiet hours, activity flag, job cancel."""

import json
from datetime import datetime

import pytest

from core import printer as P
from core.voice import action_log, proactive


@pytest.fixture
def pr(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "REQUESTS_FILE", tmp_path / "requests.json")
    monkeypatch.setattr(P, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.delenv("ARGO_H2D_ACCESS_CODE", raising=False)
    monkeypatch.setattr(P, "MIN_CONFIRM_DELAY_S", 0)
    return tmp_path


def test_a_request_sends_nothing_and_waits_for_a_yes(pr, monkeypatch):
    sent = []
    monkeypatch.setattr(P, "_send", lambda req: sent.append(req))
    req = P.request_print("Egg cup", 2, "PETG", "white")
    assert req["status"] == P.PENDING and sent == []
    assert P.describe(req) == "2 of Egg cup in white PETG"


def test_confirming_without_printer_details_saves_but_never_sends(pr, monkeypatch):
    sent = []
    monkeypatch.setattr(P, "_send", lambda req: sent.append(req))
    P.request_print("Egg cup")
    out = P.confirm_print()
    assert out["ok"] and out["sent"] is False and sent == []
    assert "IP address" in out["message"] and "access code" in out["message"]
    assert P.recent()[0]["status"] == P.WAITING


def test_confirm_sends_once_when_configured_and_never_twice(pr, monkeypatch):
    (pr / "config.json").write_text(json.dumps({"printer": {"ip": "10.0.0.5", "serial": "ABC"}}))
    monkeypatch.setenv("ARGO_H2D_ACCESS_CODE", "12345678")
    sent = []
    monkeypatch.setattr(P, "_send", lambda req: sent.append(req["id"]))
    req = P.request_print("Egg cup", 2)
    assert P.confirm_print(req["id"])["sent"] is True and len(sent) == 1
    again = P.confirm_print(req["id"])
    assert again["ok"] is False and len(sent) == 1


def test_a_failed_send_is_never_reported_as_sent(pr, monkeypatch):
    (pr / "config.json").write_text(json.dumps({"printer": {"ip": "10.0.0.5", "serial": "ABC"}}))
    monkeypatch.setenv("ARGO_H2D_ACCESS_CODE", "12345678")
    P.request_print("Egg cup")
    out = P.confirm_print()  # the real _send is not built and raises
    assert out["ok"] is False and out["sent"] is False
    assert P.recent()[0]["status"] == P.WAITING


def test_only_one_request_is_open_and_yes_means_that_one(pr):
    first = P.request_print("A")
    second = P.request_print("B")
    statuses = {r["model"]: r["status"] for r in P.recent()}
    assert statuses == {"A": P.CANCELLED, "B": P.PENDING}
    assert P.confirm_print()["request"]["id"] == second["id"]
    assert first["id"] != second["id"]


def test_inputs_are_clamped_and_cleaned(pr):
    req = P.request_print("  Cup\n\nwith   spaces ", 999, "", "red", "file:///etc/passwd")
    assert req["quantity"] == P.MAX_COPIES and req["model"] == "Cup with spaces"
    assert req["material"] == "PETG" and req["source_url"] == ""
    assert P.request_print("x", "many")["quantity"] == 1
    with pytest.raises(ValueError):
        P.request_print("   ")


def test_cancel_and_status_and_secret_never_returned(pr, monkeypatch):
    monkeypatch.setenv("ARGO_H2D_ACCESS_CODE", "supersecret")
    P.request_print("A")
    assert P.cancel_print()["ok"] and P.cancel_print()["ok"] is False
    assert "supersecret" not in json.dumps(P.settings()) and P.settings()["has_access_code"] is True
    assert P.status()["ok"] is False


def test_agent_has_the_print_tools():
    import livekit_realtime_agent as agent_mod

    for name in ("request_print", "confirm_print", "cancel_print", "printer_status"):
        assert hasattr(agent_mod.ArgoRealtimeAgent, name)


def test_quiet_hours_cross_midnight_and_can_be_turned_off():
    s = proactive.ProactiveSettings()
    at = lambda h, m=0: datetime(2026, 11, 23, h, m)
    assert proactive.in_quiet_hours(s, at(23)) and proactive.in_quiet_hours(s, at(3))
    assert proactive.in_quiet_hours(s, at(6, 59)) and not proactive.in_quiet_hours(s, at(7))
    assert not proactive.in_quiet_hours(s, at(12)) and not proactive.in_quiet_hours(s, at(21, 59))
    off = proactive.ProactiveSettings(quiet_start="08:00", quiet_end="08:00")
    assert not proactive.in_quiet_hours(off, at(3))
    daytime = proactive.ProactiveSettings(quiet_start="13:00", quiet_end="14:00")
    assert proactive.in_quiet_hours(daytime, at(13, 30)) and not proactive.in_quiet_hours(daytime, at(15))
    junk = proactive.ProactiveSettings(quiet_start="nope", quiet_end="")
    assert proactive.in_quiet_hours(junk, at(23))  # bad values fall back to 22:00-07:00


def test_a_job_that_could_not_start_is_logged_as_failed():
    assert action_log._looks_failed({"ok": True, "status": "failed", "message": "x"}, False)
    assert action_log._looks_failed({"status": "timed_out"}, False)
    assert not action_log._looks_failed({"ok": True, "status": "started"}, False)
    assert not action_log._looks_failed("plain text", False)


def test_cancel_job_rejects_bad_ids_and_cancels_through_delegate_jobs(monkeypatch):
    from core import board_service, delegate_jobs

    assert board_service.cancel_job("../etc")["ok"] is False
    assert board_service.cancel_job("")["ok"] is False
    seen = []
    monkeypatch.setattr(delegate_jobs, "cancel", lambda jid: seen.append(jid) or {"ok": True})
    assert board_service.cancel_job("abc123")["ok"] and seen == ["abc123"]


def test_a_confirm_chained_straight_after_the_request_is_refused(pr, monkeypatch):
    monkeypatch.setattr(P, "MIN_CONFIRM_DELAY_S", 4.0)
    P.request_print("Egg cup")
    out = P.confirm_print()
    assert out["ok"] is False and "Ask Tommy" in out["message"]
    assert P.recent()[0]["status"] == P.PENDING


def test_topic_titles_with_quotes_stay_readable(tmp_path, monkeypatch):
    from core import board_service as B

    monkeypatch.setattr(B, "PROJECTS_ROOT", tmp_path / "projects")
    B.add_topic_note("argo", 'The "big" one', "note")
    assert B.topics("argo")[0]["topic"] == "The 'big' one"


def test_open_app_sends_home_assistant_to_the_browser(monkeypatch):
    import webbrowser

    from core.voice import tools

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr("tools.home_assistant._base_url", lambda cfg: "http://ha.local:8123")
    assert tools._is_home_assistant("Home-Assistant") and tools._is_home_assistant("home assistant")
    assert not tools._is_home_assistant("notepad")
    assert tools.open_home_assistant() == {"ok": True, "message": "Opened Home Assistant in your browser."}
    assert opened == ["http://ha.local:8123"]
    monkeypatch.setattr("tools.home_assistant._base_url", lambda cfg: "")
    assert tools.open_home_assistant()["ok"] is False
    monkeypatch.setattr("tools.home_assistant._base_url", lambda cfg: "http://ha.local:8123")
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    assert tools.open_home_assistant()["ok"] is False
