"""Dashboard diagnostics dispatch for repair-service and legacy runtimes."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class FrontendDiagnosticsDependencies:
    get_repair_service: Callable[[], Any]
    get_diagnostics: Callable[[], Any]
    set_diagnostics: Callable[[Any], None]
    diagnostics_factory: Callable[[], Any]
    get_recovery: Callable[[], Any]
    broadcast: Callable[[str, Any], None]
    log_event: Callable[..., None]
    logger: Any


async def dispatch_frontend_diagnostics(
    dependencies: FrontendDiagnosticsDependencies,
    websocket: Any,
) -> None:
    """Run diagnostics without blocking the UI and return a structured result."""

    repair_service = dependencies.get_repair_service()
    if repair_service:
        result = await asyncio.to_thread(
            repair_service.handle_text, "Run diagnostics"
        )
        dependencies.broadcast("recovery_result", result)
        return

    try:
        diagnostics = dependencies.get_diagnostics()
        if diagnostics is None:
            diagnostics = dependencies.diagnostics_factory()
            dependencies.set_diagnostics(diagnostics)
        diagnostics.check_all()
        summary = diagnostics.get_summary()
        await websocket.send(
            json.dumps({"type": "diagnostics_result", "payload": summary})
        )
        dependencies.log_event(
            f"DIAGNOSTICS: {summary['summary']}", stage="diagnostics"
        )

        recovery = dependencies.get_recovery()
        if recovery and summary.get("errors"):
            for error in summary["errors"]:
                check = diagnostics.last_check.get(error["name"], {})
                if "recovery_action" in check.__dict__:
                    action = check.recovery_action
                    if action:
                        recovery.propose(action, error["message"])
    except Exception as exc:
        dependencies.logger.error(f"Diagnostics failed: {exc}", exc_info=True)
        await websocket.send(
            json.dumps(
                {
                    "type": "diagnostics_result",
                    "payload": {
                        "overall": "error",
                        "summary": f"Diagnostics failed: {exc}",
                    },
                }
            )
        )
