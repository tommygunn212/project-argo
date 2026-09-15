"""Resolve OPENAI_API_KEY however ARGO was launched.

The key lives in the Windows User environment here, not in .env. A process
whose parent started before that variable was set does not inherit it - and
the failure is silent in the worst possible way: the worker registers, takes
the job, and only then raises

    RuntimeError: OPENAI_API_KEY is required for OpenAI Realtime voice.

inside the job. From outside, that looks identical to "the worker never got
the job": a dispatch, a placeholder agent participant, and silence. It cost
several hours of chasing the wrong thing, including a wrong conclusion that
`start` mode was broken and `dev` was not - both of my "working" runs simply
happened to be from a shell where the key had been exported by hand.

So: read it back from the User scope when it is missing, and check it at
startup rather than at first use.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

# --- the resolver, in the guard so both entry points get it ---------------
patch("core/runtime_guard.py",
'''def venv_report() -> dict:''',
'''def ensure_openai_key() -> bool:
    """Make OPENAI_API_KEY available to this process, wherever it is stored.

    Order: the process environment, then .env, then the Windows User
    environment. That last one is where it actually lives on this machine,
    and it is the one a process started from a stale parent misses.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        if os.environ.get("OPENAI_API_KEY"):
            logger.info("[Runtime] OPENAI_API_KEY resolved from .env")
            return True
    except Exception:
        pass

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "OPENAI_API_KEY")
        if value:
            os.environ["OPENAI_API_KEY"] = value
            logger.info("[Runtime] OPENAI_API_KEY resolved from the Windows "
                        "User environment (not inherited from the parent process)")
            return True
    except Exception:
        pass

    return False


def venv_report() -> dict:''',
"runtime_guard: ensure_openai_key", marker="def ensure_openai_key(")

patch("core/runtime_guard.py",
'''    problems = []
    if not report["in_expected_venv"]:''',
'''    # Checked at STARTUP, not at first use. Missing it used to surface as a
    # job that died after being accepted, which is indistinguishable from the
    # outside from a job that was never delivered.
    report["openai_key"] = ensure_openai_key()

    problems = []
    if role == "realtime-worker" and not report["openai_key"]:
        problems.append(
            "OPENAI_API_KEY is not set anywhere this process can see it "
            "(process env, .env, or the Windows User environment). The worker "
            "would register, accept a job, and then fail inside it - which "
            "looks exactly like never receiving the job at all"
        )
    if not report["in_expected_venv"]:''',
"runtime_guard: check the key at startup", marker='report["openai_key"] = ensure_openai_key()')

# --- and at the point of use, so a long-running worker cannot lose it ------
patch("livekit_realtime_agent.py",
'''def _build_realtime_model(cfg: LiveKitRealtimeConfig) -> openai.realtime.RealtimeModel:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI Realtime voice.")''',
'''def _build_realtime_model(cfg: LiveKitRealtimeConfig) -> openai.realtime.RealtimeModel:
    from core.runtime_guard import ensure_openai_key

    ensure_openai_key()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for OpenAI Realtime voice, and it was "
            "not found in this process, in .env, or in the Windows User "
            "environment. ARGO will have accepted this job and then failed "
            "inside it, which from the room looks like no agent ever arrived."
        )''',
"agent: resolve the key at point of use", marker="ensure_openai_key()\n    api_key")

print("\n".join(log))
