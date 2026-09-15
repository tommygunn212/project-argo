"""An unrelated orphan Python process connected to LiveKit is never killed.

The first sweep stopped every parentless python.exe with a connection to
port 7880. That describes ARGO's zombie executors exactly - and also any
other LiveKit client on this machine whose parent happened to exit. These
tests pin the replacement policy:

  - by default nothing is stopped, ever; the guard reports and refuses
  - cleanup needs confirm=True, by name
  - cleanup stops only processes tied to I:\\argo by ARGO's own evidence
  - a process that merely looks like "python + dead parent + 7880" is left alone
"""

import os
from types import SimpleNamespace

import pytest

from core import runtime_guard as G


class FakeConn:
    def __init__(self, port, status="ESTABLISHED"):
        self.status = status
        self.raddr = SimpleNamespace(port=port)


class FakeProc:
    """Just enough of psutil.Process for zombie_workers() and clean_orphans()."""

    def __init__(self, pid, *, cwd, cmdline, maps, ppid=999999, port=7880, created=1_700_000_000.0):
        self.pid, self._ppid, self._cwd, self._cmd, self._maps = pid, ppid, cwd, cmdline, maps
        self._port, self._created = port, created

    def name(self): return "python.exe"
    def ppid(self): return self._ppid
    def cwd(self): return self._cwd
    def cmdline(self): return self._cmd
    def create_time(self): return self._created
    def memory_maps(self): return [SimpleNamespace(path=m) for m in self._maps]
    def net_connections(self, kind="tcp"): return [FakeConn(self._port)]


ARGO_ROOT = str(G.ROOT)
ARGO_VENV = str(G.ROOT / ".venv" / "Lib" / "site-packages" / "livekit" / "rtc" / "_lk.pyd")

ARGO_ORPHAN = dict(
    pid=4242, cwd=ARGO_ROOT,
    cmdline=["python.exe", "-c", "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=1)"],
    maps=[ARGO_VENV, r"C:\Windows\System32\kernel32.dll"],
)
UNRELATED_ORPHAN = dict(
    pid=5151, cwd=r"C:\Users\KITTY\other-livekit-project",
    cmdline=["python.exe", "-c", "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=2)"],
    maps=[r"C:\Users\KITTY\other-livekit-project\.venv\Lib\site-packages\livekit\rtc\_lk.pyd"],
)
UNRELATED_NAMED = dict(
    pid=6161, cwd=r"C:\Users\KITTY\meeting-bot",
    cmdline=["python.exe", "bot.py", "--room", "standup"],
    maps=[r"C:\Users\KITTY\meeting-bot\.venv\Lib\site-packages\livekit\rtc\_lk.pyd"],
)


@pytest.fixture
def world(monkeypatch):
    """A process table and a kill recorder, injected under the guard."""
    procs = [FakeProc(**ARGO_ORPHAN), FakeProc(**UNRELATED_ORPHAN), FakeProc(**UNRELATED_NAMED)]
    killed = []
    monkeypatch.setattr(G, "_process_iter", lambda: list(procs))
    monkeypatch.setattr(G, "_kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(G, "livekit_port", lambda: 7880)

    import psutil

    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == os.getpid())
    by_pid = {p.pid: p for p in procs}
    monkeypatch.setattr(psutil, "Process", lambda pid: by_pid[pid])
    return SimpleNamespace(procs=procs, killed=killed)


# --- identification --------------------------------------------------------

def test_all_three_are_suspected_but_only_argo_is_confirmed(world):
    found = {z["pid"]: z for z in G.zombie_workers()}
    assert set(found) == {4242, 5151, 6161}, "all three look like python+dead parent+7880"
    assert found[4242]["confirmed"] is True
    assert found[5151]["confirmed"] is False
    assert found[6161]["confirmed"] is False


def test_argo_evidence_is_argo_specific(world):
    found = {z["pid"]: z for z in G.zombie_workers()}
    assert found[4242]["cwd_is_argo"] and found[4242]["argo_venv_mapped"]
    for pid in (5151, 6161):
        assert not found[pid]["cwd_is_argo"]
        assert not found[pid]["argo_venv_mapped"]
        assert not found[pid]["cmdline_is_argo"]


def test_argo_cwd_alone_is_not_enough(world, monkeypatch):
    """Right folder, but nothing of ARGO's loaded and nothing ARGO in argv."""
    lookalike = FakeProc(7171, cwd=ARGO_ROOT, cmdline=["python.exe", "scratch.py"],
                         maps=[r"C:\Python311\python311.dll"])
    monkeypatch.setattr(G, "_process_iter", lambda: world.procs + [lookalike])
    found = {z["pid"]: z for z in G.zombie_workers()}
    assert found[7171]["confirmed"] is False


def test_a_process_with_a_living_parent_is_never_listed(world, monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)   # every parent alive
    assert G.zombie_workers() == []


# --- the default: refuse, never kill -----------------------------------------

def test_default_cleanup_refuses_and_stops_nothing(world):
    result = G.clean_orphans()
    assert "requires confirm=True" in result["refused"]
    assert result["stopped"] == []
    assert world.killed == []


def test_verify_runtime_refuses_startup_and_kills_nothing(world, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "prefix", str(G.EXPECTED_VENV))
    monkeypatch.setattr(G, "check_imports", lambda role: {})
    monkeypatch.setattr(G, "ensure_openai_key", lambda: True)

    with pytest.raises(G.RuntimeProblem) as raised:
        G.verify_runtime("realtime-worker")
    text = str(raised.value)
    assert "Nothing has been stopped" in text
    assert "4242" in text and "5151" in text and "6161" in text
    assert "NOT confirmed as ARGO" in text
    assert "-CleanOrphans" in text
    assert world.killed == []


# --- explicit cleanup: only ARGO, and prove the unrelated ones survive -------

def test_explicit_cleanup_stops_only_the_confirmed_argo_orphan(world):
    result = G.clean_orphans(confirm=True)
    assert world.killed == [4242], f"killed {world.killed}; only ARGO's own executor may be stopped"
    assert [z["pid"] for z in result["stopped"]] == [4242]
    assert {z["pid"] for z in result["left_alone"]} == {5151, 6161}


def test_unrelated_orphan_survives_even_when_it_is_the_only_one(world, monkeypatch):
    monkeypatch.setattr(G, "_process_iter", lambda: [FakeProc(**UNRELATED_ORPHAN)])
    result = G.clean_orphans(confirm=True)
    assert world.killed == []
    assert [z["pid"] for z in result["left_alone"]] == [5151]


def test_a_recycled_pid_is_not_killed(world, monkeypatch):
    """Identified as ARGO, then the pid is reused by something else before the
    kill. The start time no longer matches - so it must be skipped."""
    import psutil

    recycled = FakeProc(4242, cwd=r"C:\Users\KITTY\newthing", cmdline=["python.exe", "x.py"],
                        maps=[], created=1_800_000_000.0)
    original = psutil.Process
    monkeypatch.setattr(psutil, "Process", lambda pid: recycled if pid == 4242 else original(pid))
    result = G.clean_orphans(confirm=True)
    assert world.killed == []
    assert result["confirmed"][0]["skipped"] == "pid was recycled since it was identified"


def test_evidence_lost_at_kill_time_means_no_kill(world, monkeypatch):
    import psutil

    drifted = FakeProc(4242, cwd=r"C:\elsewhere", cmdline=["python.exe"], maps=[],
                       created=ARGO_ORPHAN.get("created", 1_700_000_000.0))
    original = psutil.Process
    monkeypatch.setattr(psutil, "Process", lambda pid: drifted if pid == 4242 else original(pid))
    result = G.clean_orphans(confirm=True)
    assert world.killed == []
    assert "no longer identifiable" in result["confirmed"][0]["skipped"]


# --- the CLI the launcher calls -------------------------------------------------

def test_report_mode_is_read_only(world, capsys):
    code = G._cli(["--report"])
    assert code == 2                       # orphans present -> refuse
    assert world.killed == []
    out = capsys.readouterr().out
    assert "nothing stopped" in out and "5151" in out


def test_clean_mode_prints_every_decision(world, capsys):
    code = G._cli(["--clean"])
    out = capsys.readouterr().out
    assert world.killed == [4242]
    assert "stopped  pid 4242" in out
    assert "left     pid 5151" in out and "left     pid 6161" in out
    assert code == 2                       # something was left alone -> tell the caller
