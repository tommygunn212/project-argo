"""Make the proof test dispatch for real, and close the release-on-exit gap."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if new.strip().splitlines()[0].strip() in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

# 1. The lock should be given up on a clean shutdown, not left for the next
#    start to reclaim by liveness check.
patch("main.py",
'''    finally:
        logger.info("Main thread exiting")''',
'''    finally:
        try:
            _instance_lock.release()
        except Exception:
            pass
        logger.info("Main thread exiting")''',
"main.py: release the lock on exit")

# 2. The doctor can only see a room the browser has opened, so on its own it
#    can never prove dispatch works - it skips when Tommy is not connected.
#    The probe creates its own room and dispatches into it, which is the half
#    that does not need a human.
patch("tools/prove_voice.py",
'''def check_tests(rep: Report) -> None:''',
'''def check_dispatch(rep: Report) -> None:
    """Can the worker actually be dispatched into a room right now?

    This is the check that would have caught the real fault. "Worker
    registered" and "worker takes jobs" are different claims, and only the
    second one means ARGO can hear anything.
    """
    log = rep.dir / "dispatch_probe.log"
    code, output = run([PY, "tools/dispatch_probe.py"], log, timeout=120)
    joined = "PASS - agent" in output
    detail = ""
    for line in output.splitlines():
        if line.startswith("PASS - agent") or line.startswith("FAIL - no agent"):
            detail = line.strip()
            break
    rep.step("the worker can be dispatched into a room", code == 0 and joined,
             detail or f"exit {code}, see {log.name}", log=log.name)


def check_tests(rep: Report) -> None:''',
"prove_voice: add the dispatch probe")

patch("tools/prove_voice.py",
'''    rep.say()
    rep.say("-- local LiveKit --")
    check_doctor(rep)''',
'''    rep.say()
    rep.say("-- local LiveKit --")
    check_dispatch(rep)
    check_doctor(rep)''',
"prove_voice: run the probe before the doctor")

# 3. The doctor needs a browser in the room, so an empty server is a SKIP and
#    not a failure - the probe above is what carries the hard verdict.
patch("tools/prove_voice.py",
'''    rep.step("an agent is in the room", code == 0,
             "every occupied room has an agent" if code == 0 else f"see {log.name}",
             log=log.name)''',
'''    if "has 1 human participant" in output or "has " in output and "NO agent" in output:
        rep.step("an agent is in the room with Tommy", code == 0,
                 "a browser is connected with no agent - reconnect Smooth Voice"
                 if code else "every occupied room has an agent", log=log.name)
        return
    rep.step("an agent is in the room with Tommy", None if code else True,
             "no browser connected, so nothing to check here - the dispatch "
             "probe above is the hard verdict" if code else "rooms all healthy",
             log=log.name)''',
"prove_voice: doctor skips without a browser")

# 4. Guard health belongs in the report too.
patch("tools/prove_voice.py",
'''    check_urgent_interrupts(rep)''',
'''    check_urgent_interrupts(rep)
    check_runtime_guard(rep)''',
"prove_voice: call the guard check")

patch("tools/prove_voice.py",
'''def check_classic_is_gated(rep: Report) -> None:''',
'''def check_runtime_guard(rep: Report) -> None:
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


def check_classic_is_gated(rep: Report) -> None:''',
"prove_voice: guard check body")

print("\n".join(log))
