"""Three patches my own skip-heuristic swallowed. Exact anchors, no guessing."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label} (marker already present)"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

patch("main.py",
'''    finally:
        logger.info("Main thread exiting")''',
'''    finally:
        try:
            _instance_lock.release()
        except Exception:
            pass
        logger.info("Main thread exiting")''',
"main.py: release the lock on exit", marker="_instance_lock.release()")

patch("tools/prove_voice.py",
'''    rep.say("-- local LiveKit --")
    check_doctor(rep)''',
'''    rep.say("-- local LiveKit --")
    check_dispatch(rep)
    check_doctor(rep)''',
"prove_voice: actually call the dispatch probe", marker="    check_dispatch(rep)\n    check_doctor(rep)")

patch("tools/prove_voice.py",
'''    check_urgent_interrupts(rep)
    check_deep_think(rep)''',
'''    check_urgent_interrupts(rep)
    check_runtime_guard(rep)
    check_deep_think(rep)''',
"prove_voice: actually call the guard check", marker="    check_runtime_guard(rep)\n    check_deep_think(rep)")

print("\n".join(log))

# --- verify by reading back, not by trusting the write --------------------
print("\n--- call-site audit ---")
pv = io.open(ROOT / "tools" / "prove_voice.py", encoding="utf-8").read()
mn = io.open(ROOT / "main.py", encoding="utf-8").read()
for label, ok in [
    ("check_dispatch defined",  "def check_dispatch(" in pv),
    ("check_dispatch called",   "\n    check_dispatch(rep)" in pv),
    ("check_runtime_guard defined", "def check_runtime_guard(" in pv),
    ("check_runtime_guard called",  "\n    check_runtime_guard(rep)" in pv),
    ("lock released on exit",   "_instance_lock.release()" in mn),
]:
    print(f"  {'OK  ' if ok else 'MISS'} {label}")
