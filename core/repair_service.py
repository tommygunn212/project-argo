"""One diagnostic and approval conversation shared by UI and voice paths."""
import asyncio
import re
import threading
import time
import os

from core.intent_parser import detect_self_diagnostics
from core.self_diagnostics import SystemDiagnostics, ComponentHealth, HealthStatus


class ActiveDiagnostics(SystemDiagnostics):
    """Inspect selected components without warming models or opening audio."""
    def __init__(self, pipeline):
        super().__init__()
        self.pipeline = pipeline

    def check_all(self):
        import sounddevice as sd
        pipeline = self.pipeline
        results = {"disk_space": self._check_disk_space(), "memory": self._check_memory()}
        router = getattr(pipeline, "_llm_router", None)
        chain = router.provider_chain() if router else []
        if not chain:
            results["llm"] = ComponentHealth("llm", HealthStatus.ERROR, "No enabled conversational provider")
        else:
            primary = chain[0]
            if primary.provider == "ollama" and not primary.base_url:
                results["ollama"] = self._check_ollama()
            else:
                keys = {"openai": ("OPENAI_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}.get(primary.provider, ())
                present = any(os.getenv(key) for key in keys)
                results["llm"] = ComponentHealth("llm", HealthStatus.WARNING if present or not keys else HealthStatus.ERROR,
                    f"{primary.provider} selected; " + ("credentials missing" if keys and not present else "live response not tested by basic checks"))
        stt = getattr(pipeline, "stt_engine_manager", None)
        results["stt"] = ComponentHealth("stt", HealthStatus.OK if stt and stt.model is not None else HealthStatus.ERROR,
            "Selected STT loaded; transcription not exercised" if stt and stt.model is not None else "Selected STT is not loaded",
            recovery_action="restart_stt" if stt else None)
        tts = getattr(pipeline, "_tts_engine", "unknown")
        ready = tts != "openai" or getattr(pipeline, "_openai_tts", None) is not None
        results["tts"] = ComponentHealth("tts", HealthStatus.WARNING if ready else HealthStatus.ERROR,
            f"{tts} TTS selected; audible output not tested" if ready else "OpenAI TTS client is not initialized",
            recovery_action="restart_tts" if not ready else None)
        for direction in ("input", "output"):
            name = "audio_" + direction
            try:
                device = getattr(pipeline.audio, "_" + direction + "_device_index")
                if device is None:
                    raise RuntimeError("No selected device")
                info = sd.query_devices(device)
                if info.get("max_" + direction + "_channels", 0) < 1:
                    raise RuntimeError("Selected device has no channels")
                results[name] = ComponentHealth(name, HealthStatus.OK,
                    f"Selected {direction} device exists: {info['name']} (no live audio test)")
            except Exception as exc:
                results[name] = ComponentHealth(name, HealthStatus.ERROR,
                    f"Selected {direction} device check failed: {exc}", recovery_action="reinit_audio")
        self.last_check, self.last_check_time = results, time.time()
        return results


class RepairService:
    def __init__(self, recovery, code_repairs, broadcast, diagnostics_factory=SystemDiagnostics):
        self.recovery = recovery
        self.code_repairs = code_repairs
        self.broadcast = broadcast
        self.diagnostics_factory = diagnostics_factory
        self.lock = threading.Lock()
        self.last_report = ""
        self.last_problem = ""

    def diagnose(self, problem="Run diagnostics"):
        with self.lock:
            self.last_problem = problem
            self.recovery.pending_proposals.clear()
            diagnostic = self.diagnostics_factory()
            diagnostic.check_all()
            summary = diagnostic.get_summary()
            self.broadcast("diagnostics_result", summary)
            for health in diagnostic.last_check.values():
                if health.status.value == "error" and health.recovery_action:
                    proposal = self.recovery.propose(health.recovery_action, health.message)
                    if proposal:
                        self.last_report = (f"Check found: {health.message}. Proposed action: {proposal.proposal}. "
                            "Say 'approve repair' or 'cancel repair', or use System in the dashboard.")
                        return {"status": "proposed", "message": self.last_report, "proposal": proposal.to_dict(), "diagnostics": summary}
            if self.recovery.retry_callback:
                proposal = self.recovery.propose("retry_last", "The last conversational response failed.")
                self.last_report = "The last conversational response failed. Say 'approve repair' to retry that response, or 'cancel repair'."
                return {"status": "proposed", "message": self.last_report, "proposal": proposal.to_dict(), "diagnostics": summary}
            self.last_report = (f"Basic checks: {summary['summary']}. These checks have not reproduced your reported problem. "
                "Say 'prepare code repair' to record it for Astra, or describe the symptom more specifically.")
            return {"status": "unresolved", "message": self.last_report, "diagnostics": summary}

    def respond(self, proposal_id, approved):
        if not self.lock.acquire(blocking=False):
            return {"status": "error", "message": "A repair check is already running."}
        try:
            result = asyncio.run(self.recovery.execute_if_approved(proposal_id, approved))
            if approved is True and result.get("status") in ("success", "warning"):
                try:
                    diagnostic = self.diagnostics_factory()
                    diagnostic.check_all()
                    verification = diagnostic.get_summary()
                    result["verification"] = verification
                    self.broadcast("diagnostics_result", verification)
                    if verification["overall"] == "ok":
                        result["status"] = "checks_passed"
                        result["message"] += " Post-repair basic checks pass. Please try the original symptom again."
                    else:
                        result["status"] = "unresolved"
                        result["message"] += " Post-repair checks still report: " + verification["summary"]
                except Exception as exc:
                    result.update(status="unverified", message=f"Action finished, but verification failed: {exc}")
            self.last_report = result.get("message", "Repair status unavailable.")
            self.broadcast("recovery_result", result)
            return result
        finally:
            self.lock.release()

    def handle_text(self, text):
        try:
            return self._handle_text(text)
        except Exception as exc:
            self.last_report = f"Repair check could not complete: {exc}"
            result = {"status": "error", "message": self.last_report}
            self.broadcast("recovery_result", result)
            return result

    def _handle_text(self, text):
        normalized = re.sub(r"[.!?,]+$", "", text.lower().strip())
        normalized = re.sub(r"^argo[, ]+", "", normalized)
        if normalized in ("approve repair", "cancel repair"):
            pending = list(self.recovery.pending_proposals.values())
            if len(pending) != 1:
                return {"status": "error", "message": "No single pending runtime repair. Ask me to diagnose again."}
            return self.respond(pending[0].proposal_id, normalized == "approve repair")
        if normalized in ("repair status", "what happened to the repair"):
            return {"status": "status", "message": self.last_report or "No runtime repair yet. Code-repair progress is in System."}
        if normalized == "prepare code repair":
            if not self.last_problem:
                return {"status": "error", "message": "Describe the broken behavior first."}
            job = self.code_repairs.propose(self.last_problem + "\nDiagnostic finding: " + self.last_report)
            return {"status": "proposed", "message": "Code repair recorded. Review the request in System and approve Astra there.", "job": job}
        if detect_self_diagnostics(text):
            return self.diagnose(text)
        return None
