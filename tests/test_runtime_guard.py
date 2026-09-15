"""The venv check must not fail the process that is actually correct.

This suite exists because of a specific mistake worth not repeating. On
Windows, I:\\argo\\.venv\\Scripts\\python.exe is venvlauncher.exe - a stub that
re-executes the BASE interpreter and waits on it. So a correctly launched ARGO
looks like this:

    sys.executable   C:\\...\\Python311\\python.exe   <- base, looks wrong
    sys.prefix       I:\\argo\\.venv                  <- venv, is right

Reading the process list, that pair looks exactly like "a second copy running
on the wrong interpreter". It is not. A guard written against sys.executable
would kill the only working process; a report written against it recommended
exactly that. sys.prefix decides which site-packages get imported, so
sys.prefix is what these tests pin.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from core import runtime_guard as G


# --- the venv check -------------------------------------------------------

def test_the_stub_pattern_is_accepted_not_flagged(monkeypatch):
    """The real shape of a healthy Windows ARGO process."""
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(sys, "executable", r"C:\Python311\python.exe")
    monkeypatch.setattr(sys, "_base_executable", r"C:\Python311\python.exe", raising=False)

    report = G.venv_report()
    assert report["in_expected_venv"] is True, (
        "a base-interpreter executable with a venv prefix is CORRECT on Windows"
    )


def test_a_genuinely_wrong_interpreter_is_caught(monkeypatch):
    monkeypatch.setattr(sys, "prefix", r"C:\Python311")
    assert G.venv_report()["in_expected_venv"] is False


def test_verify_runtime_refuses_to_start_outside_the_venv(monkeypatch):
    monkeypatch.setattr(sys, "prefix", r"C:\Python311")
    monkeypatch.setattr(G, "check_imports", lambda role: {})

    with pytest.raises(G.RuntimeProblem) as raised:
        G.verify_runtime("realtime-worker")
    assert "packages live in" in str(raised.value)
    assert str(G.EXPECTED_VENV) in str(raised.value)


def test_verify_runtime_refuses_a_worker_that_cannot_import_livekit(monkeypatch):
    """A worker missing livekit.plugins still REGISTERS and still takes jobs -
    it just cannot run them. Refusing to start is the loud failure."""
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports",
                        lambda role: {"livekit.plugins.openai": "ModuleNotFoundError: no"})

    with pytest.raises(G.RuntimeProblem) as raised:
        G.verify_runtime("realtime-worker")
    assert "cannot import livekit.plugins.openai" in str(raised.value)


def test_a_healthy_process_passes_and_reports(monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})

    report = G.verify_runtime("realtime-worker")
    assert report["problems"] == []
    assert report["role"] == "realtime-worker"


def test_this_very_process_is_in_the_venv():
    """Not a mock: the interpreter running these tests must be ARGO's."""
    report = G.venv_report()
    assert report["in_expected_venv"], (
        f"tests are running from {report['prefix']}, not {report['expected_prefix']}"
    )


def test_the_worker_can_import_everything_it_needs():
    assert G.check_imports("realtime-worker") == {}


# --- one at a time --------------------------------------------------------

@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "LOCK_DIR", tmp_path / "locks")
    return tmp_path / "locks"


def test_a_lock_is_taken_and_released(lock_dir):
    lock = G.SingleInstance("realtime-worker")
    with lock:
        assert lock.path.exists()
        assert json.loads(lock.path.read_text())["pid"] == os.getpid()
    assert not lock.path.exists()


def test_a_second_worker_is_refused(lock_dir):
    """The failure this whole module exists for: two workers registering as
    argo-realtime makes dispatch a coin flip."""
    with G.SingleInstance("realtime-worker"):
        with pytest.raises(G.RuntimeProblem) as raised:
            G.SingleInstance("realtime-worker").acquire()
    assert "already running" in str(raised.value)


def test_different_roles_do_not_block_each_other(lock_dir):
    with G.SingleInstance("main"):
        with G.SingleInstance("realtime-worker"):
            assert True


def test_a_stale_lock_from_a_dead_process_is_reclaimed(lock_dir):
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "realtime-worker.lock").write_text(json.dumps({
        "role": "realtime-worker", "pid": 999999,
        "started": time.time(), "started_human": "whenever",
    }), encoding="utf-8")

    with G.SingleInstance("realtime-worker") as lock:
        assert json.loads(lock.path.read_text())["pid"] == os.getpid()


def test_a_recycled_pid_is_not_mistaken_for_a_live_argo(lock_dir):
    """Windows reuses PIDs. Without the start-time check, an unrelated process
    that inherits the old PID would keep ARGO from ever starting again."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "main.lock").write_text(json.dumps({
        "role": "main", "pid": os.getpid(),
        # This PID is alive, but it did not start in 1999 - so it is not the
        # process that wrote this lock.
        "started": 915148800.0, "started_human": "1999-01-01 00:00:00",
    }), encoding="utf-8")

    with G.SingleInstance("main") as lock:
        assert json.loads(lock.path.read_text())["pid"] == os.getpid()


def test_takeover_is_possible_when_explicitly_asked(lock_dir):
    first = G.SingleInstance("main").acquire()
    try:
        second = G.SingleInstance("main", takeover=True).acquire()
        assert json.loads(second.path.read_text())["pid"] == os.getpid()
    finally:
        first.release()


def test_the_lock_records_enough_to_find_the_other_process(lock_dir):
    with G.SingleInstance("main") as lock:
        held = json.loads(lock.path.read_text())
    assert held["executable"] and held["prefix"] and held["started_human"]
