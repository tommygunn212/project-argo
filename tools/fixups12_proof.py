"""Fold the lifecycle test and the zombie check into the proof run."""
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

patch("tools/prove_voice.py",
'''def check_dispatch(rep: Report) -> None:''',
'''def check_zombies(rep: Report) -> None:
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


def check_dispatch(rep: Report) -> None:''',
"prove_voice: zombie + lifecycle checks", marker="def check_lifecycle(")

patch("tools/prove_voice.py",
'''    rep.say("-- local LiveKit --")
    check_dispatch(rep)
    check_doctor(rep)''',
'''    rep.say("-- local LiveKit --")
    check_zombies(rep)
    check_dispatch(rep)
    check_doctor(rep)
    check_lifecycle(rep)''',
"prove_voice: call them", marker="    check_zombies(rep)\n")

# The lifecycle test owns its own worker; the dispatch probe needs the stack's
# worker. They cannot share one. Make the lifecycle check drain whatever is
# running first and note it - the launcher restarts the stack afterwards.
patch("tools/prove_voice.py",
'''    log = rep.dir / "lifecycle.log"
    code, output = run([PY, "-u", "tools/lifecycle_test.py", "-n", str(dispatches), "--settle", "6"],''',
'''    rep.say("   (the lifecycle test drains the running worker and starts its own; "
            "run scripts\\\\start_argo_stack.ps1 afterwards)")
    log = rep.dir / "lifecycle.log"
    code, output = run([PY, "-u", "tools/lifecycle_test.py", "-n", str(dispatches), "--settle", "6"],''',
"prove_voice: lifecycle note", marker="drains the running worker and starts its own")

print("\n".join(log))
import ast; ast.parse(io.open(ROOT / "tools" / "prove_voice.py", encoding="utf-8").read()); print("prove_voice parses")
