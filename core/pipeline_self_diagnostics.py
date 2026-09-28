"""Self-diagnostics response stage for the classic pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from core.self_diagnostics import AssistedRecovery, SystemDiagnostics


class SelfDiagnosticsPipeline(Protocol):
    """Minimal pipeline surface required by self-diagnostics routing."""

    logger: Any
    recovery_manager: Any

    def broadcast(self, event: str, payload: Any) -> None: ...

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool: ...


def respond_with_self_diagnostics(
    pipeline: SelfDiagnosticsPipeline,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict | None,
) -> bool:
    """Phase 1 & 2: ARGO checks itself and reports status.
    
    Runs diagnostics on all components (Ollama, Piper, Whisper, audio).
    If problems found, proposes assisted recovery (requires user permission).
    """
    def _finish(message: str) -> bool:
        return pipeline._deliver_canonical_response(
            message,
            interaction_id,
            replay_mode,
            overrides,
            enforce_confidence=False,
            force_tts=True,
        )
    
    try:
        diag = SystemDiagnostics()
        diag.check_all()
        summary = diag.get_summary()
        
        # Broadcast full results to UI
        pipeline.broadcast("diagnostics_result", summary)
        
        # Build spoken response
        overall = summary.get("overall", "unknown")
        if overall == "ok":
            response = f"All systems operational. {summary.get('ok_count', 0)} components checked, all healthy."
        elif overall == "warning":
            warnings = summary.get("warnings", [])
            if warnings:
                warn_names = ", ".join(w["name"] for w in warnings[:3])
                response = f"Systems mostly okay. Warnings on: {warn_names}."
            else:
                response = "Systems okay with minor warnings."
        elif overall == "error":
            errors = summary.get("errors", [])
            if errors:
                # Report first error with fix
                first_error = errors[0]
                err_name = first_error.get("name", "component")
                err_msg = first_error.get("message", "has an issue")
                err_fix = first_error.get("fix", "")
                
                response = f"Problem detected: {err_name} {err_msg}."
                if err_fix:
                    response += f" Suggested fix: {err_fix}."
                
                # Propose recovery if available
                for comp_name, comp_health in diag.last_check.items():
                    if comp_health.status.value == "error" and comp_health.recovery_action:
                        # The server installs one shared manager so the
                        # proposal here is the same proposal the UI approves.
                        recovery = getattr(pipeline, "recovery_manager", None)
                        if recovery is None:
                            recovery = AssistedRecovery(pipeline=pipeline, broadcast_fn=pipeline.broadcast)
                        proposal = recovery.propose(
                            comp_health.recovery_action,
                            comp_health.message
                        )
                        if proposal:
                            response += f" Want me to try restarting {err_name}?"
                        break
            else:
                response = "There's a problem but I couldn't identify it."
        else:
            response = "Diagnostics complete but status unclear."
        
        pipeline.logger.info(f"[SELF_DIAGNOSTICS] {overall}: {summary.get('summary', '')}")
        return _finish(response)
        
    except Exception as e:
        pipeline.logger.error(f"[SELF_DIAGNOSTICS] Failed: {e}", exc_info=True)
        return _finish("I tried to check myself but something went wrong.")

