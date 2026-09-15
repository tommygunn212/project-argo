"""Wire the runtime guard into both entry points, then audit that every
change from this session is genuinely on disk.

Written as an on-box patch because the file-transfer path silently wrote
stale copies three times - reporting success while leaving the old bytes in
place. Anything that matters gets verified by reading the file back, not by
trusting the write.
"""
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
log = []


def patch(rel, old, new, label):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if new.strip().splitlines()[0] in s and "runtime_guard" in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")


patch("main.py",
'''    _restore_voice_mode()
    _start_main_loop_thread()''',
'''    # Refuse to start wrong rather than start broken. The check reads
    # sys.PREFIX, not sys.executable: on Windows the venv python is a stub
    # that re-executes the base interpreter, so a perfectly healthy ARGO
    # reports a base-interpreter executable. Reading that as "wrong
    # interpreter" is how you end up killing the only working process.
    from core.runtime_guard import SingleInstance, verify_runtime

    verify_runtime("main")
    _instance_lock = SingleInstance("main").acquire()

    _restore_voice_mode()
    _start_main_loop_thread()''',
"main.py: guard + lock")

patch("main.py",
'''    finally:
        logger.info("Main thread exiting")''',
'''    finally:
        try:
            _instance_lock.release()
        except Exception:
            pass
        logger.info("Main thread exiting")''',
"main.py: release lock on exit")

patch("livekit_realtime_agent.py",
'''if __name__ == "__main__":
    # Built here, not at import. build_agent_server() calls _apply_livekit_env,
    # which mutates os.environ, and opens a LiveKit AgentServer - importing this
    # module to inspect its tools or to test them should do neither.
    cli.run_app(build_agent_server())''',
'''if __name__ == "__main__":
    # Guarded here rather than in build_agent_server(): the framework's idle
    # job executors import this module, and they must not each take the lock
    # or re-run the environment check.
    #
    # The lock is the important half. A second worker registering under the
    # same agent_name fails silently - LiveKit just hands the job to whichever
    # it likes, so "can ARGO hear me" becomes a coin flip and both workers'
    # logs look identical either way.
    from core.runtime_guard import SingleInstance, verify_runtime

    verify_runtime("realtime-worker")
    with SingleInstance("realtime-worker"):
        # Built here, not at import. build_agent_server() calls
        # _apply_livekit_env, which mutates os.environ, and opens a LiveKit
        # AgentServer - importing this module to inspect its tools or to test
        # them should do neither.
        cli.run_app(build_agent_server())''',
"agent: guard + lock")

print("\n".join(log))

# --- audit: is everything from this session actually on disk? --------------
print("\n--- on-disk audit ---")
EXPECTED = [
    ("main.py", "runtime_guard", "runtime guard wired"),
    ("main.py", "CLASSIC_TURN_DROPPED", "classic turn drop gate"),
    ("main.py", "and VOICE_MODE != VOICE_MODE_SMOOTH", "classic capture gate"),
    ("livekit_realtime_agent.py", "runtime_guard", "runtime guard wired"),
    ("livekit_realtime_agent.py", "matches_urgent_phrase", "urgent interrupt fast path"),
    ("livekit_realtime_agent.py", "_build_turn_detection", "semantic vad builder"),
    ("livekit_realtime_agent.py", "fallback_model", "automatic model fallback"),
    ("livekit_realtime_agent.py", "think_deeply", "deep think tool"),
    ("core/livekit_config.py", "urgent_interrupt_phrases", "urgent phrases config"),
    ("core/livekit_config.py", "DEEP_THINK_BRIEF", "deep think brief"),
    ("core/livekit_config.py", "cleared stale dispatch", "stale dispatch fix"),
    ("core/deep_think.py", "def cancel_all", "deep think module"),
    ("core/runtime_guard.py", "Deliberately NOT exempting", "lock same-pid fix"),
    ("core/filesystem_access.py", "path_shape_problem", "path containment"),
    ("core/realtime_tools.py", "PathRefused", "refused paths as answers"),
    ("personas/argo.py", "ArgoPersona", "collaborator persona"),
]
missing = []
for rel, needle, label in EXPECTED:
    p = ROOT / rel
    ok = p.exists() and needle in io.open(p, encoding="utf-8", errors="replace").read()
    print(f"  {'OK  ' if ok else 'MISS'} {rel:<32} {label}")
    if not ok:
        missing.append(f"{rel}: {label}")
print(f"\n{len(EXPECTED) - len(missing)}/{len(EXPECTED)} present")
if missing:
    print("MISSING:")
    for m in missing:
        print("  -", m)
