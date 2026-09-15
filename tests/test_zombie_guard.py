"""The guard must refuse to start a worker into a zombie pool.

Eight orphaned executor processes, each still registered with LiveKit under
the same agent name, gave ARGO 2 sessions in 10 dispatches. A worker that
starts next to them is joining a lottery. verify_runtime() has to say so and
stop, with the pids, rather than register and go quiet.
"""

import sys

import pytest

from core import runtime_guard as G


def test_the_current_process_is_never_a_zombie():
    assert all(z["pid"] != __import__("os").getpid() for z in G.zombie_workers())


def test_zombie_report_has_what_you_need_to_act():
    for z in G.zombie_workers():
        assert z["pid"] and z["started"] and "cmdline" in z


def test_a_worker_refuses_to_start_into_a_zombie_pool(monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})
    monkeypatch.setattr(G, "ensure_openai_key", lambda: True)
    monkeypatch.setattr(G, "zombie_workers", lambda: [
        {"pid": 4242, "started": "2026-09-13 16:47:03", "cmdline": "python -c spawn_main", "confirmed": True},
        {"pid": 4343, "started": "2026-09-14 02:01:47", "cmdline": "python -c spawn_main", "confirmed": False},
    ])
    with pytest.raises(G.RuntimeProblem) as raised:
        G.verify_runtime("realtime-worker")
    text = str(raised.value)
    assert "2 parentless python process" in text and "4242" in text and "4343" in text
    assert "Nothing has been stopped" in text
    assert "-CleanOrphans" in text


def test_main_does_not_care_about_zombies(monkeypatch):
    """Only the worker competes for jobs; the backend must still start."""
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})
    monkeypatch.setattr(G, "zombie_workers", lambda: [{"pid": 1, "started": "x", "cmdline": "y"}])
    assert G.verify_runtime("main")["problems"] == []


def test_a_clean_pool_passes(monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})
    monkeypatch.setattr(G, "ensure_openai_key", lambda: True)
    monkeypatch.setattr(G, "zombie_workers", lambda: [])
    assert G.verify_runtime("realtime-worker")["problems"] == []


def test_the_report_never_carries_a_key(monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})
    monkeypatch.setattr(G, "zombie_workers", lambda: [])
    report = G.verify_runtime("realtime-worker", fatal=False)
    flat = repr(report)
    assert "sk-" not in flat
    assert report["openai_key"] in (True, False)   # a boolean, never the value
