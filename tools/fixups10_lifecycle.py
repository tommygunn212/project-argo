"""Instrument the worker's job path and give it a graceful drain.

Every event the lifecycle test needs comes from the worker itself:
  job_received        the entrypoint ran for this job (job_id, dispatch_id, room, pid)
  model_built         the realtime model constructed (model name only)
  model_build_failed  it did not (exception type + sanitized message)
  session_start       already emitted; the AgentSession is up
  session_end         the framework shut the job down (reason)

And one control: a drain file. The test writes runtime/locks/realtime-worker.drain;
a daemon thread in the worker sees it and raises SIGINT *in-process*, which is
the framework's own shutdown path (_ExitCli -> server.drain() -> aclose()).
That deregisters the worker from LiveKit properly. No TerminateProcess, no
Stop-Process -Force, no zombie registrations left behind by the test itself.
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
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

AGENT = "livekit_realtime_agent.py"

# --- 1. job_received: first thing in the entrypoint, before config ---------
patch(AGENT,
'''async def _run_realtime_session(ctx: JobContext) -> None:
    _ensure_logging()
    cfg = get_livekit_realtime_config()''',
'''def _safe_error(exc: BaseException) -> str:
    """An exception message with anything key-shaped removed."""
    import re

    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"sk-[A-Za-z0-9_\\-]{8,}", "sk-***", text)
    text = re.sub(r"eyJ[A-Za-z0-9_\\-]{8,}\\.[A-Za-z0-9_\\-]{8,}\\.[A-Za-z0-9_\\-]{8,}", "***jwt***", text)
    return text[:400]


async def _run_realtime_session(ctx: JobContext) -> None:
    _ensure_logging()
    # Emitted before anything else can fail, so "the entrypoint ran" is
    # separable from "the model built" and "the session started". The
    # lifecycle test correlates on room name; every event carries the pid.
    from core import voice_events as _ve

    job = getattr(ctx, "job", None)
    _ve.emit(
        "job_received",
        job_id=str(getattr(job, "id", "") or ""),
        dispatch_id=str(getattr(job, "dispatch_id", "") or ""),
        room=str(getattr(getattr(job, "room", None), "name", "") or ""),
    )

    async def _on_shutdown(reason: str = "") -> None:
        _ve.emit("session_end", room=str(getattr(getattr(job, "room", None), "name", "") or ""),
                 job_id=str(getattr(job, "id", "") or ""), reason=str(reason or ""))

    try:
        ctx.add_shutdown_callback(_on_shutdown)
    except Exception:
        logger.debug("[Session] could not register shutdown callback", exc_info=True)

    cfg = get_livekit_realtime_config()''',
"agent: job_received + session_end", marker='"job_received"')

# --- 2. model build result ---------------------------------------------------
patch(AGENT,
'''    session = AgentSession(
        llm=_build_realtime_model(cfg),''',
'''    try:
        realtime_llm = _build_realtime_model(cfg)
    except Exception as exc:
        _ve.emit("model_build_failed", model=cfg.model, error=_safe_error(exc))
        raise
    _ve.emit("model_built", model=cfg.model, voice=cfg.voice)

    session = AgentSession(
        llm=realtime_llm,''',
"agent: model_built / model_build_failed", marker='"model_built"')

# --- 3. drain-file watcher -----------------------------------------------------
patch(AGENT,
'''    verify_runtime("realtime-worker")
    with SingleInstance("realtime-worker"):''',
'''    verify_runtime("realtime-worker")

    def _watch_for_drain() -> None:
        """Graceful stop on request, without a console or a kill.

        The framework shuts down on SIGINT: _ExitCli -> server.drain() ->
        server.aclose(), which deregisters this worker from LiveKit. On
        Windows nothing outside the process can deliver that signal to a
        hidden, redirected process - but the process can raise it on itself.
        So: a file appears, this thread raises SIGINT, the main thread takes
        the normal shutdown path. The file is removed first so a stale one
        cannot stop the next start.
        """
        import signal
        import time as _time

        drain_file = ROOT / "runtime" / "locks" / "realtime-worker.drain"
        while True:
            _time.sleep(0.5)
            try:
                if drain_file.exists():
                    try:
                        drain_file.unlink()
                    except Exception:
                        pass
                    logger.warning("[Lifecycle] drain requested - shutting down gracefully")
                    from core import voice_events as _ve
                    _ve.emit("drain_requested")
                    signal.raise_signal(signal.SIGINT)
                    return
            except Exception:
                logger.debug("[Lifecycle] drain watcher error", exc_info=True)

    import threading as _threading

    _threading.Thread(target=_watch_for_drain, name="argo-drain-watcher", daemon=True).start()

    with SingleInstance("realtime-worker"):''',
"agent: drain-file watcher", marker="realtime-worker.drain")

# --- 4. say which worker registered, so the test can match pid <-> worker id --
patch(AGENT,
'''    server.rtc_session(_run_realtime_session, agent_name=cfg.agent_name)
    return server''',
'''    server.rtc_session(_run_realtime_session, agent_name=cfg.agent_name)

    try:
        from core import voice_events as _ve

        _ve.emit("worker_built", agent_name=cfg.agent_name, url=cfg.url, model=cfg.model)
    except Exception:
        pass
    return server''',
"agent: worker_built event", marker='"worker_built"')

print("\n".join(log))
s = io.open(ROOT / AGENT, encoding="utf-8").read()
import ast; ast.parse(s)
print("\n--- read-back ---")
for needle, label in [('"job_received"', "job_received"), ('"session_end"', "session_end"),
                      ('"model_built"', "model_built"), ('"model_build_failed"', "model_build_failed"),
                      ("realtime-worker.drain", "drain watcher"), ('"worker_built"', "worker_built"),
                      ("def _safe_error", "_safe_error")]:
    print(f"  {'OK  ' if needle in s else 'MISS'} {label}")
