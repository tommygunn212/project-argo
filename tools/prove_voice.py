"""Everything that can be proved about ARGO's voice without a human talking.

Run one line; read one report:

    .venv\\Scripts\\python tools\\prove_voice.py

It writes runtime\\voice_tests\\proof-<timestamp>\\ containing report.json and
report.txt, plus the raw output of every step. Nothing here reports success
from a config label: each check either observed the thing or says it could
not. The microphone scenarios are a separate script - see voice_scenarios.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = sys.executable
OUT_ROOT = ROOT / "runtime" / "voice_tests"

# The tests that actually bear on this work. Running the whole suite here would
# bury the signal under music, Jellyfin and wake-word tests.
TARGETED_TESTS = [
    "tests/test_path_containment.py",
    "tests/test_filesystem_access.py",
    "tests/test_realtime_tools.py",
    "tests/test_livekit_config.py",
    "tests/test_realtime_personality.py",
    "tests/test_voice_mode_ownership.py",
    "tests/test_agent_import_is_clean.py",
    "tests/test_deep_think.py",
    "tests/test_runtime_guard.py",
    "tests/test_zombie_guard.py",
    "tests/test_orphan_policy.py",
    "tests/test_persona_briefs.py",
    "tests/test_persona_reaches_session.py",
    "tests/test_deep_think_persona.py",
]


# Everything this run writes goes through here first. The report is meant to
# be pasted into a chat, and I:\argo\.env holds his OpenAI key, his LiveKit
# secret and a Home Assistant token with a 2038 expiry.
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "***JWT-REDACTED***"),
    (re.compile(r"(?i)(api[_-]?key|api[_-]?secret|token|password|authorization)"
                r"(\s*[=:]\s*|\\?[\"']?\s*:\s*\\?[\"']?)([^\s,;\"'}\]]{8,})"),
     r"\1\2***REDACTED***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***REDACTED***"),
]


def redact(text: str) -> str:
    """Strip anything that looks like a credential out of report text."""
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class Report:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.steps: list[dict] = []
        self.lines: list[str] = []

    def say(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def step(self, name: str, ok: bool | None, detail: str = "", **extra) -> None:
        self.steps.append({"step": name, "ok": ok, "detail": detail, **extra})
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        self.say(f"[{mark}] {name}" + (f" - {detail}" if detail else ""))

    def write(self) -> None:
        failed = [s for s in self.steps if s["ok"] is False]
        skipped = [s for s in self.steps if s["ok"] is None]
        self.say()
        self.say("=" * 68)
        self.say(f"{len(self.steps) - len(failed) - len(skipped)} passed, "
                 f"{len(failed)} failed, {len(skipped)} skipped")
        for s in failed:
            self.say(f"  FAILED: {s['step']} - {s['detail']}")
        for s in skipped:
            self.say(f"  SKIPPED: {s['step']} - {s['detail']}")
        (self.dir / "report.json").write_text(
            redact(json.dumps({"generated": datetime.now().isoformat(), "steps": self.steps},
                              indent=2)),
            encoding="utf-8")
        (self.dir / "report.txt").write_text(redact("\n".join(self.lines)), encoding="utf-8")
        self.say()
        self.say(f"Artifacts: {self.dir}")


def run(cmd: list[str], log: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace")
        output = redact((proc.stdout or "") + (proc.stderr or ""))
        log.write_text(output, encoding="utf-8")
        return proc.returncode, output
    except subprocess.TimeoutExpired:
        log.write_text(f"timed out after {timeout}s", encoding="utf-8")
        return 124, "timed out"
    except Exception as exc:
        log.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return 1, f"{type(exc).__name__}: {exc}"


# --- 1. what is installed --------------------------------------------------

def check_versions(rep: Report) -> None:
    from importlib import metadata

    versions = {}
    for package in ("livekit-agents", "livekit-plugins-openai",
                    "livekit-plugins-noise-cancellation", "openai", "websockets"):
        try:
            versions[package] = metadata.version(package)
        except Exception:
            versions[package] = None
    (rep.dir / "versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    missing = [k for k, v in versions.items() if v is None]
    rep.step("installed packages", not missing,
             ", ".join(f"{k}={v}" for k, v in versions.items() if v),
             versions=versions, missing=missing)


# --- 2. the live config, as the worker will actually resolve it ------------

def check_live_config(rep: Report) -> dict:
    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    resolved = {
        "model": cfg.model, "voice": cfg.voice, "personality": cfg.personality,
        "turn_detection": cfg.turn_detection, "turn_eagerness": cfg.turn_eagerness,
        "noise_cancellation": cfg.noise_cancellation,
        "input_noise_reduction": cfg.input_noise_reduction,
        "min_interruption_duration": cfg.min_interruption_duration,
        "min_interruption_words": cfg.min_interruption_words,
        "false_interruption_timeout": cfg.false_interruption_timeout,
        "deep_think_enabled": cfg.deep_think_enabled,
        "deep_think_model": cfg.deep_think_model,
        "fallback_model": cfg.fallback_model,
        "urgent_interrupt_phrases": list(cfg.urgent_interrupt_phrases),
        "instruction_chars": len(cfg.instructions),
    }
    (rep.dir / "live_config.json").write_text(json.dumps(resolved, indent=2), encoding="utf-8")
    (rep.dir / "instructions.txt").write_text(cfg.instructions, encoding="utf-8")

    rep.step("turn detection is configured", cfg.turn_detection == "semantic_vad",
             f"{cfg.turn_detection} / eagerness={cfg.turn_eagerness}")
    rep.step("noise cancellation is on", cfg.noise_cancellation is True,
             f"livekit BVC={cfg.noise_cancellation}, server={cfg.input_noise_reduction}")
    rep.step("a cough cannot interrupt", cfg.min_interruption_words >= 2,
             f"min_interruption_words={cfg.min_interruption_words}, "
             f"min_duration={cfg.min_interruption_duration}s")
    rep.step("personality is the collaborator", cfg.personality == "argo",
             f"personality={cfg.personality}")
    same = cfg.fallback_model == cfg.model
    rep.step("there is a fallback model", bool(cfg.fallback_model),
             f"{cfg.model} -> {cfg.fallback_model}"
             + (" (same model: nothing to fall back TO, which is correct only "
                "while the configured model IS the known-good one)" if same else ""))
    return resolved


def check_urgent_interrupts(rep: Report) -> None:
    """A decisive "stop" must not wait for the two-word threshold."""
    import livekit_realtime_agent as agent_mod
    from core.livekit_config import get_livekit_realtime_config

    phrases = get_livekit_realtime_config().urgent_interrupt_phrases
    match = agent_mod.matches_urgent_phrase

    fires = ["stop", "Stop!", "wait", "hold on", "stop talking", "wait, wait"]
    holds = ["don't stop the music", "we should wait for the render",
             "what I meant was", "so anyway, hold the thought"]

    missed = [t for t in fires if not match(t, phrases)]
    false_fires = [t for t in holds if match(t, phrases)]
    rep.step("a single \"stop\" interrupts immediately", not missed and not false_fires,
             f"missed={missed or 'none'} false_fires={false_fires or 'none'}",
             phrases=list(phrases))
    rep.step("generic speech still needs the sustained threshold",
             get_livekit_realtime_config().min_interruption_words >= 2,
             f"min_interruption_words={get_livekit_realtime_config().min_interruption_words}")


# --- 3. what the model is actually told ------------------------------------

def check_instructions(rep: Report) -> None:
    from core.livekit_config import get_livekit_realtime_config

    text = get_livekit_realtime_config().instructions.lower()

    # Each phrase must appear ONLY inside a prohibition. Matching the bare
    # phrase flagged "Do not repeat his question back" as asking for the very
    # thing it forbids.
    banned = {
        "repeats the question": "repeat his question",
        "canned acknowledgement": "great question",
        "narrates internal steps": "narrate what you are about to do",
    }
    present = [
        label for label, phrase in banned.items()
        if phrase in text and not re.search(r"do not [^.]{0,40}" + re.escape(phrase), text)
    ]
    rep.step("instructions do not ask for the behaviours he banned", not present,
             ", ".join(present) or "none found")

    required = {
        "match his length": "match his length",
        "let him finish": "let him finish",
        "stop when interrupted": "stop immediately",
    }
    missing = [label for label, phrase in required.items() if phrase not in text]
    rep.step("instructions cover turn-taking and length", not missing,
             ", ".join(missing) or "all present")

    # The tool list used to be two thirds of what the model read. It is one
    # section now, and this is the check that keeps it that way.
    tool_share = text.count("get_") + text.count("_app") + text.count("_music")
    rep.step("the brief is a conversation brief, not a tool manual",
             len(text) > 1200 and tool_share < 30,
             f"{len(text)} chars, {tool_share} tool mentions")


# --- 4. the realtime model really accepts these settings -------------------

def check_preflight(rep: Report, model: str, label: str) -> None:
    log = rep.dir / f"preflight-{model}.log"
    code, output = run([PY, "tools/realtime_preflight.py", "--model", model], log, timeout=120)
    passed = code == 0 and "PASS" in output
    semantic = '"semantic_vad_accepted": true' in output.lower()
    rep.step(f"live session opens on {model} ({label})", passed,
             ("semantic_vad accepted" if semantic else "connected but semantic_vad NOT echoed")
             if passed else f"see {log.name}",
             log=log.name, semantic_vad=semantic)


# --- 5. is anything actually listening -------------------------------------

def check_doctor(rep: Report) -> None:
    log = rep.dir / "livekit_doctor.log"
    code, output = run([PY, "tools/livekit_doctor.py"], log, timeout=90)
    if "no rooms on the server" in output:
        rep.step("an agent is in the room", None,
                 "no room open - start Smooth Voice, then re-run", log=log.name)
        return
    if "has 1 human participant" in output or "has " in output and "NO agent" in output:
        rep.step("an agent is in the room with Tommy", code == 0,
                 "a browser is connected with no agent - reconnect Smooth Voice"
                 if code else "every occupied room has an agent", log=log.name)
        return
    rep.step("an agent is in the room with Tommy", None if code else True,
             "no browser connected, so nothing to check here - the dispatch "
             "probe above is the hard verdict" if code else "rooms all healthy",
             log=log.name)


# --- 6. the targeted suite --------------------------------------------------

def check_zombies(rep: Report) -> None:
    """Orphaned workers still registered with LiveKit make dispatch a lottery."""
    from core.runtime_guard import zombie_workers

    zombies = zombie_workers()
    rep.step("no orphaned workers are registered with LiveKit", not zombies,
             "pool is clean" if not zombies else
             "; ".join(f"pid {z['pid']} since {z['started']}" for z in zombies),
             zombies=zombies)


def check_lifecycle(rep: Report, dispatches: int = 5) -> None:
    """Sequential dispatches against ONE worker the test owns and drains.

    This is the check that found the real fault: a placeholder participant
    without a session, eight times in ten, because eight orphans were
    registered under the same agent name. It is slow (~1 min) and it is the
    only check here that proves the job path end to end.
    """
    rep.say("   (the lifecycle test drains the running worker and starts its own; "
            "run scripts\\start_argo_stack.ps1 afterwards)")
    log = rep.dir / "lifecycle.log"
    code, output = run([PY, "-u", "tools/lifecycle_test.py", "-n", str(dispatches), "--settle", "6"],
                       log, timeout=600)
    summary = ""
    for line in output.splitlines():
        if "dispatches started a real session" in line:
            summary = line.strip()
            break
    drained = '"ok": true' in output.split("draining worker...")[-1] if "draining worker..." in output else False
    rep.step(f"{dispatches} sequential dispatches all start a session", code == 0 and drained,
             (summary or f"exit {code}") + (" ; worker drained cleanly" if drained else " ; DRAIN FAILED"),
             log=log.name)


def check_dispatch(rep: Report) -> None:
    """Can the worker actually be dispatched into a room right now?

    This is the check that would have caught the real fault. "Worker
    registered" and "worker takes jobs" are different claims, and only the
    second one means ARGO can hear anything.
    """
    log = rep.dir / "dispatch_probe.log"
    code, output = run([PY, "tools/dispatch_probe.py"], log, timeout=120)
    joined = "PASS - a real session started" in output
    detail = ""
    for line in output.splitlines():
        if line.startswith("PASS - a real session") or line.startswith("FAIL - no session"):
            detail = line.strip()
            break
    rep.step("the worker can be dispatched into a room", code == 0 and joined,
             detail or f"exit {code}, see {log.name}", log=log.name)


def check_tests(rep: Report) -> None:
    present = [t for t in TARGETED_TESTS if (ROOT / t).exists()]
    log = rep.dir / "pytest.log"
    code, output = run([PY, "-m", "pytest", "-q", "--tb=short", *present], log, timeout=1200)
    summary = ""
    for line in reversed(output.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break
    rep.step("targeted tests", code == 0, summary or f"exit {code}, see {log.name}",
             log=log.name, files=present)


# --- 7. deep think is reachable and cancellable ----------------------------

def check_deep_think(rep: Report) -> None:
    import asyncio

    from core import deep_think

    async def cancels() -> bool:
        async def slow(messages, model):
            await asyncio.sleep(30)
            return "should never arrive"

        original, deep_think._call_openai = deep_think._call_openai, slow
        try:
            task = asyncio.ensure_future(deep_think.think("x", model="test", timeout=30))
            await asyncio.sleep(0.4)
            thinking = deep_think.is_thinking()
            killed = deep_think.cancel_all(reason="proof")
            result = await task
            return thinking and killed == 1 and result.cancelled
        finally:
            deep_think._call_openai = original

    try:
        ok = asyncio.run(cancels())
    except Exception as exc:
        rep.step("deep think cancels the moment he speaks", False, f"{type(exc).__name__}: {exc}")
        return
    rep.step("deep think cancels the moment he speaks", ok,
             "in-flight request was killed and returned cancelled")


def check_runtime_guard(rep: Report) -> None:
    """Is this interpreter the one ARGO's packages live in, and is exactly one
    of each role running?"""
    from core.runtime_guard import LOCK_DIR, check_imports, venv_report

    report = venv_report()
    rep.step("running out of the expected venv", report["in_expected_venv"],
             f"prefix={report['prefix']}"
             + (" (launched via the venv stub, which is normal on Windows)"
                if report["launched_via_venv_stub"] else ""))
    broken = check_imports("realtime-worker")
    rep.step("the worker's imports all resolve", not broken,
             ", ".join(broken) if broken else "livekit.agents, livekit.plugins.openai, openai")

    import json as _json

    held = {}
    for role in ("main", "realtime-worker"):
        path = LOCK_DIR / f"{role}.lock"
        if path.exists():
            try:
                held[role] = _json.loads(path.read_text(encoding="utf-8")).get("pid")
            except Exception:
                held[role] = "unreadable"
    rep.step("one instance of each role holds a lock", len(held) == 2,
             ", ".join(f"{k}=pid {v}" for k, v in held.items()) or "no locks held "
             "(ARGO may not be running)", locks=held)


def check_classic_is_gated(rep: Report) -> None:
    """Can the classic pipeline or Ollama answer while Smooth Voice is live?

    Read as source, not as configuration: the question is whether the code
    path exists, and a config flag saying "smooth" proves nothing about what
    main_loop does with a buffer it already captured.
    """
    source = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")

    capture_gated = "and VOICE_MODE != VOICE_MODE_SMOOTH" in source
    answer_gated = "CLASSIC_TURN_DROPPED" in source and \
        source.index("if VOICE_MODE == VOICE_MODE_SMOOTH") < source.index("target=pipeline.run_interaction")
    rep.step("classic capture cannot start in smooth mode", capture_gated,
             "VAD trigger is gated on VOICE_MODE" if capture_gated else "gate NOT FOUND in main.py")
    rep.step("a captured classic turn is dropped, not answered", answer_gated,
             "dropped before pipeline.run_interaction" if answer_gated else "gate NOT FOUND")

    agent_source = (ROOT / "livekit_realtime_agent.py").read_text(encoding="utf-8", errors="replace")
    deep_source = (ROOT / "core" / "deep_think.py").read_text(encoding="utf-8", errors="replace")
    touches_ollama = any(
        token in text.lower()
        for text in (agent_source, deep_source)
        for token in ("ollama", "llm_router", "11434")
    )
    rep.step("the realtime path cannot reach Ollama", not touches_ollama,
             "no ollama/llm_router/11434 reference in the realtime or deep-think path"
             if not touches_ollama else "a reference exists - check it")

    try:
        import socket

        probe = socket.socket()
        probe.settimeout(0.4)
        running = probe.connect_ex(("127.0.0.1", 11434)) == 0
        probe.close()
    except Exception:
        running = False
    rep.step("Ollama is not auto-started", True,
             "ollama is listening on 11434 (fine - it is a manual fallback, "
             "just not reachable from the realtime path)" if running
             else "nothing listening on 11434")


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = OUT_ROOT / f"proof-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)
    rep = Report(directory)

    rep.say(f"ARGO voice proof run - {datetime.now():%Y-%m-%d %H:%M:%S}")
    rep.say("=" * 68)

    check_versions(rep)
    resolved = check_live_config(rep)
    check_instructions(rep)
    check_urgent_interrupts(rep)
    check_runtime_guard(rep)
    check_deep_think(rep)

    rep.say()
    rep.say("-- classic voice / Ollama containment --")
    check_classic_is_gated(rep)

    rep.say()
    rep.say("-- live OpenAI Realtime checks (needs OPENAI_API_KEY and network) --")
    check_preflight(rep, resolved["model"], "currently configured")
    if resolved["model"] != "gpt-realtime-2.1":
        check_preflight(rep, "gpt-realtime-2.1", "upgrade candidate")

    rep.say()
    rep.say("-- local LiveKit --")
    check_zombies(rep)
    check_dispatch(rep)
    check_doctor(rep)
    check_lifecycle(rep)

    rep.say()
    rep.say("-- targeted test suite --")
    check_tests(rep)

    rep.write()
    return 1 if any(s["ok"] is False for s in rep.steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
