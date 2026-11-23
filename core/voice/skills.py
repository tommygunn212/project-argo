"""Skills: tools Argo wrote for herself, loaded when a session starts.

The folder is ``argo_skills/`` at the repo root. See its README for the file
shape. Everything here is defensive on purpose - a skill is code written by an
AI at 1 a.m., so loading one must never be able to stop ARGO starting, hang a
turn, or shadow a built-in tool.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import inspect
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "argo_skills"
SKILL_LOG = ROOT / "runtime" / "logs" / "skills.jsonl"
SKILL_TIMEOUT_S = 90.0
MAX_TOOLS_PER_SKILL = 8
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")

logger = logging.getLogger("ARGO.Skills")

# The contract Codex is given when it builds a skill. Kept next to the loader
# that enforces it so the two cannot drift apart.
SKILL_CONTRACT = """\
You are adding ONE new skill (a voice tool) to ARGO, a realtime voice assistant.

Write exactly two files, and nothing else:
  argo_skills/{name}.py        the skill
  tests/test_skill_{name}.py   pytest tests for it

Skill file contract (enforced by core/voice/skills.py - read it first):
- A module-level list `TOOLS = [fn, ...]` of plain `async def` functions.
- Every function has type hints and a clear docstring. The docstring is what
  tells the voice model WHEN to call it, so start with what it does and say
  when Tommy would ask for it. Keep parameters simple (str, int, float, bool).
- Return a short plain string the assistant can say aloud, or a dict.
- Tool names must not collide with ARGO's built-in tools (see
  core/voice/tools.py and core/voice/agent.py) and must be snake_case.
- Use only the Python standard library and packages already installed in .venv
  (aiohttp, openai, httpx are available). Do NOT pip install anything.
- Secrets: read OPENAI_API_KEY with core.runtime_guard.ensure_openai_key(); never
  hard-code or print a key.
- Do not touch the microphone, ARGO's config, or any file outside this repo's
  runtime/ folder at run time. Network calls are fine if the feature needs them.
- To show something on Tommy's dashboard, use core.voice.show.show_image /
  show_html if they exist; otherwise just return text.

Tests must run offline (mock any network call) and finish in seconds. They must
import the skill and call its tools directly. Run them with:
  .venv\\Scripts\\python.exe -m pytest tests/test_skill_{name}.py -q
and make them pass before you finish. Report the exact command and result.
"""


def _log(event: str, **fields: Any) -> None:
    try:
        SKILL_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {"t": time.time(), "clock": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "event": event, **fields}
        with SKILL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(str(name or "")))


def _guard(fn, skill: str):
    """Run a skill tool with a time limit; turn any failure into text."""

    @functools.wraps(fn)
    async def run(*args, **kwargs):
        started = time.time()
        try:
            out = await asyncio.wait_for(fn(*args, **kwargs), SKILL_TIMEOUT_S)
            ok = True
        except asyncio.TimeoutError:
            out, ok = {"ok": False, "error": f"{fn.__name__} timed out after {SKILL_TIMEOUT_S:.0f}s"}, False
        except Exception as exc:  # a skill must never crash the session
            out, ok = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, False
        _log("call", skill=skill, tool=fn.__name__, ok=ok, seconds=round(time.time() - started, 2))
        return out if isinstance(out, str) else json.dumps(out, default=str)

    return run


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"argo_skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot build an import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover(reserved: set[str] | None = None, directory: Path | None = None):
    """Import every skill. Returns ``(tools, report)``.

    ``reserved`` is the set of names already taken by built-in tools. ``report``
    is a list of ``{"skill", "ok", "tools" | "error"}`` dicts, one per file.
    """
    from livekit.agents import function_tool

    folder = directory or SKILLS_DIR
    reserved = set(reserved or ())
    tools: list = []
    report: list[dict] = []
    seen: set[str] = set()
    if not folder.is_dir():
        return tools, report
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        try:
            if not valid_name(name):
                raise ValueError("file name must be snake_case, 3-31 chars")
            module = _load_module(path)
            funcs = list(getattr(module, "TOOLS", None) or [])
            if not funcs:
                raise ValueError("no TOOLS list")
            if len(funcs) > MAX_TOOLS_PER_SKILL:
                raise ValueError(f"more than {MAX_TOOLS_PER_SKILL} tools")
            built, names = [], []
            for fn in funcs:
                if not inspect.iscoroutinefunction(fn):
                    raise TypeError(f"{getattr(fn, '__name__', fn)!r} is not an async def")
                if not (inspect.getdoc(fn) or "").strip():
                    raise ValueError(f"{fn.__name__} has no docstring")
                if fn.__name__ in reserved or fn.__name__ in seen:
                    raise ValueError(f"tool name {fn.__name__!r} is already taken")
                built.append(function_tool(_guard(fn, name)))
                names.append(fn.__name__)
            tools.extend(built)
            seen.update(names)
            report.append({"skill": name, "ok": True, "tools": names})
        except Exception as exc:
            report.append({"skill": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            logger.warning("[Skills] skipped %s: %s", name, exc)
            _log("skipped", skill=name, error=f"{type(exc).__name__}: {exc}")
    return tools, report


def load_for_session(reserved: set[str] | None = None):
    """What a new voice session calls. Never raises."""
    try:
        tools, report = discover(reserved)
    except Exception as exc:
        logger.warning("[Skills] loader failed: %s", exc, exc_info=True)
        return [], []
    good = [r for r in report if r["ok"]]
    bad = [r for r in report if not r["ok"]]
    if report:
        logger.info("[Skills] %d loaded (%d tools), %d skipped",
                    len(good), len(tools), len(bad))
    _log("session_load", loaded=[r["skill"] for r in good], skipped=[r["skill"] for r in bad])
    return tools, report


def install(name: str, files: dict[str, bytes], *, directory: Path | None = None,
            tests_directory: Path | None = None) -> dict:
    """Put a verified skill (and its test) into the live folders.

    The previous version of the skill, if any, is kept in ``_history``.
    ``files`` maps repo-relative paths to bytes.
    """
    folder = directory or SKILLS_DIR
    tests = tests_directory or (ROOT / "tests")
    if not valid_name(name):
        raise ValueError("bad skill name")
    want_skill, want_test = f"argo_skills/{name}.py", f"tests/test_skill_{name}.py"
    if set(files) - {want_skill, want_test} or want_skill not in files:
        raise ValueError("a skill job may only write its skill file and its test")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.py"
    replaced = target.exists()
    if replaced:
        history = folder / "_history"
        history.mkdir(exist_ok=True)
        (history / f"{name}.{time.strftime('%Y%m%d-%H%M%S')}.py").write_bytes(target.read_bytes())
    target.write_bytes(files[want_skill])
    if want_test in files:
        tests.mkdir(exist_ok=True)
        (tests / f"test_skill_{name}.py").write_bytes(files[want_test])
    _log("installed", skill=name, replaced=replaced, bytes=len(files[want_skill]))
    return {"skill": name, "replaced": replaced, "path": str(target)}


def builtin_tool_names() -> set[str]:
    """Names ARGO's own tools use, so a skill can't shadow one."""
    try:
        from core.voice.tools import CapabilityTools
        from livekit.agents import Agent

        names = {n for n in dir(CapabilityTools) if not n.startswith("_")}
        names |= {n for n in dir(Agent) if not n.startswith("_")}
        names |= {"delegate_task", "check_background_tasks", "cancel_background_task",
                  "recall", "repair_argo", "improve_argo", "work_on_project",
                  "argo_roadmap", "think_deeply", "build_skill", "list_my_skills"}
        return names
    except Exception:
        return set()
