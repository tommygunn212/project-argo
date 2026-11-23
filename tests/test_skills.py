"""Argo's self-built skills: the loader, the install step, and the build pipeline."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.code_repair import CodeRepairManager
from core.voice import skills

GOOD = '''"""Flip a coin."""
import random

async def flip_coin(sides: int = 2) -> str:
    """Flip a coin or roll a die. Use when Tommy asks for a coin flip."""
    return str(random.randint(1, sides))

TOOLS = [flip_coin]
'''


def write(folder: Path, name: str, body: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def log_to_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "SKILL_LOG", tmp_path / "skills.jsonl")


def test_good_skill_loads_and_runs(tmp_path):
    write(tmp_path, "flip_coin", GOOD)
    tools, report = skills.discover(set(), tmp_path)
    assert report == [{"skill": "flip_coin", "ok": True, "tools": ["flip_coin"]}]
    assert len(tools) == 1
    assert tools[0].info.name == "flip_coin"
    assert int(asyncio.run(tools[0](sides=6))) in range(1, 7)


@pytest.mark.parametrize("body, why", [
    ("raise RuntimeError('boom at import')", "boom"),
    ("TOOLS = []", "no TOOLS"),
    ("def f(x: int) -> str:\n    'doc'\n    return ''\nTOOLS = [f]", "not an async def"),
    ("async def f(x: int) -> str:\n    return ''\nTOOLS = [f]", "no docstring"),
    ("async def play_music(x: int) -> str:\n    'doc'\n    return ''\nTOOLS = [play_music]", "already taken"),
    ("def broken(:\n", "SyntaxError"),
])
def test_broken_skills_are_skipped_not_fatal(tmp_path, body, why):
    write(tmp_path, "bad_one", body)
    write(tmp_path, "flip_coin", GOOD)  # a good neighbour must still load
    tools, report = skills.discover({"play_music"}, tmp_path)
    bad = next(r for r in report if r["skill"] == "bad_one")
    assert bad["ok"] is False and why.lower() in bad["error"].lower()
    assert [r["skill"] for r in report if r["ok"]] == ["flip_coin"]
    assert len(tools) == 1


def test_two_skills_cannot_share_a_tool_name(tmp_path):
    write(tmp_path, "aaa_coin", GOOD)
    write(tmp_path, "bbb_coin", GOOD)
    _tools, report = skills.discover(set(), tmp_path)
    assert [r["ok"] for r in report] == [True, False]


def test_underscore_files_and_bad_filenames_are_ignored_or_refused(tmp_path):
    write(tmp_path, "_helper", "raise RuntimeError('never imported')")
    write(tmp_path, "BadName", GOOD)
    _tools, report = skills.discover(set(), tmp_path)
    assert [r["skill"] for r in report] == ["BadName"] and report[0]["ok"] is False


def test_errors_and_timeouts_become_text_not_crashes(tmp_path, monkeypatch):
    write(tmp_path, "crashy", '''
import asyncio
async def explode() -> str:
    """Always fails."""
    raise ValueError("nope")
async def hang() -> str:
    """Never finishes."""
    await asyncio.sleep(60)
TOOLS = [explode, hang]
''')
    monkeypatch.setattr(skills, "SKILL_TIMEOUT_S", 0.2)
    tools, _ = skills.discover(set(), tmp_path)
    out = [json.loads(asyncio.run(t())) for t in tools]
    assert out[0] == {"ok": False, "error": "ValueError: nope"}
    assert out[1]["ok"] is False and "timed out" in out[1]["error"]


def test_builtin_names_cover_real_tools():
    names = skills.builtin_tool_names()
    assert {"play_music", "improve_argo", "build_skill", "delegate_task"} <= names


def test_install_keeps_history_and_rejects_stray_files(tmp_path):
    live, tests = tmp_path / "argo_skills", tmp_path / "tests"
    one = {"argo_skills/flip_coin.py": GOOD.encode(), "tests/test_skill_flip_coin.py": b"def test_x(): pass\n"}
    assert skills.install("flip_coin", one, directory=live, tests_directory=tests)["replaced"] is False
    assert skills.install("flip_coin", one, directory=live, tests_directory=tests)["replaced"] is True
    assert len(list((live / "_history").glob("flip_coin.*.py"))) == 1
    with pytest.raises(ValueError):
        skills.install("flip_coin", {**one, "core/evil.py": b"x"}, directory=live, tests_directory=tests)
    with pytest.raises(ValueError):
        skills.install("../escape", one, directory=live, tests_directory=tests)


# --- the build pipeline, with a fake Codex that writes real files -----------

@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "repo"
    directory.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "Test")
    (directory / ".gitignore").write_text("runtime/\n__pycache__/\n", encoding="utf-8")
    (directory / "core").mkdir()
    (directory / "core" / "__init__.py").write_text("", encoding="utf-8")
    (directory / "keep.py").write_text("X = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "baseline")
    return directory


def run_skill_job(monkeypatch, repo, *, files, test_body, name="flip_coin"):
    done = threading.Event()
    manager = CodeRepairManager(repo, lambda kind, payload: done.set() if kind == "code_repair_result" else None,
                                timeout=60, auto_apply=True)
    original = subprocess.Popen

    def launch(command, **kwargs):
        if command[0] != "fixture-codex":
            return original(command, **kwargs)
        assert "argo_skills" in command[-1] and "tests/test_skill_flip_coin.py" in command[-1]
        result = command[command.index("-o") + 1]
        script = "from pathlib import Path\n" + "".join(
            f"Path({rel!r}).parent.mkdir(parents=True, exist_ok=True)\nPath({rel!r}).write_text({body!r}, encoding='utf-8')\n"
            for rel, body in files.items()) + f"Path({str(result)!r}).write_text('done')\n"
        return original([sys.executable, "-c", script], **kwargs)

    # the verification step needs the real loader, which lives in the real repo
    real_root = Path(skills.__file__).resolve().parents[2]
    monkeypatch.setattr("core.code_repair.shutil.which", lambda _: "fixture-codex")
    monkeypatch.setattr("core.code_repair.subprocess.Popen", launch)
    job = manager.propose("Flip a coin when I ask", skill_name=name)
    assert manager.dispatch_if_approved(job["action_id"], True)["status"] == "running"
    assert done.wait(60), manager.snapshot()
    return manager, manager.snapshot()[0], real_root


def test_pipeline_installs_a_passing_skill_into_a_dirty_repo(monkeypatch, repo):
    # Tommy is mid-edit: a dirty tracked file must not matter.
    (repo / "keep.py").write_text("X = 999  # work in progress\n", encoding="utf-8")
    # Point the verification at the real loader/venv by running from a copy of core.
    import shutil
    shutil.copytree(Path(skills.__file__).resolve().parents[1], repo / "core", dirs_exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "add", "core"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "real core"], check=True)
    (repo / "keep.py").write_text("X = 999  # work in progress\n", encoding="utf-8")
    test_body = ("import asyncio, importlib.util, pathlib\n"
                 "def test_flip():\n"
                 "    p = pathlib.Path('argo_skills/flip_coin.py')\n"
                 "    spec = importlib.util.spec_from_file_location('flip_coin', p)\n"
                 "    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                 "    assert int(asyncio.run(m.TOOLS[0](sides=6))) in range(1, 7)\n")
    manager, job, _ = run_skill_job(monkeypatch, repo, files={
        "argo_skills/flip_coin.py": GOOD, "tests/test_skill_flip_coin.py": test_body}, test_body=test_body)
    assert job["status"] == "applied" and job["skill_installed"] is True, job
    assert (repo / "argo_skills" / "flip_coin.py").read_text() == GOOD
    assert (repo / "keep.py").read_text().startswith("X = 999")  # his edit untouched
    assert "installed" in skills.SKILL_LOG.read_text()
    # recorded on a separate branch without touching the checked-out one
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "argo-self"],
                              capture_output=True, text=True).stdout
    assert "argo-self" in branches
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == "main"


def test_pipeline_refuses_a_skill_that_touches_other_files(monkeypatch, repo):
    import shutil
    shutil.copytree(Path(skills.__file__).resolve().parents[1], repo / "core", dirs_exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "add", "core"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "real core"], check=True)
    manager, job, _ = run_skill_job(monkeypatch, repo, files={
        "argo_skills/flip_coin.py": GOOD,
        "tests/test_skill_flip_coin.py": "def test_ok():\n    assert True\n",
        "keep.py": "X = 'tampered'\n"}, test_body="")
    assert job["status"] == "review_failed"
    assert "keep.py" in job["skill_problem"]
    assert not (repo / "argo_skills" / "flip_coin.py").exists()


def test_pipeline_refuses_a_skill_whose_test_fails(monkeypatch, repo):
    import shutil
    shutil.copytree(Path(skills.__file__).resolve().parents[1], repo / "core", dirs_exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "add", "core"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "real core"], check=True)
    manager, job, _ = run_skill_job(monkeypatch, repo, files={
        "argo_skills/flip_coin.py": GOOD,
        "tests/test_skill_flip_coin.py": "def test_bad():\n    assert False\n"}, test_body="")
    assert job["status"] == "review_failed" and job["test_exit"] != 0
    assert not (repo / "argo_skills" / "flip_coin.py").exists()


def test_service_rejects_bad_skill_names():
    from core.repair_service import RepairService
    service = RepairService.__new__(RepairService)
    service.code_repairs = SimpleNamespace(propose=lambda *a, **k: pytest.fail("must not propose"))
    assert service.propose_skill_request("../etc", "x")["status"] == "error"
    assert service.propose_skill_request("A", "x")["status"] == "error"
