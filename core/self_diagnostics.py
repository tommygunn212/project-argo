# ============================================================================
# ARGO Self-Diagnostics and Assisted Recovery
# ============================================================================
# Phase 1: Diagnostic Awareness - detect and explain problems
# Phase 2: Assisted Recovery - propose fixes, ask permission, execute if approved
#
# CRITICAL CONSTRAINT: No autonomous actions. Every fix requires user permission.
# ============================================================================

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import psutil
import requests


logger = logging.getLogger("self_diagnostics")


# ============================================================================
# Data Structures
# ============================================================================

class HealthStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class RecoveryRisk(Enum):
    LOW = "low"       # Restart, retry - always safe
    MEDIUM = "medium" # Reinit - usually safe
    HIGH = "high"     # Not allowed in Phase 2


@dataclass
class ComponentHealth:
    """Health status of a single component"""
    name: str
    status: HealthStatus
    message: str
    details: dict = field(default_factory=dict)
    suggested_fix: Optional[str] = None
    recovery_action: Optional[str] = None  # Action ID if fix available


@dataclass
class RecoveryProposal:
    """A proposed recovery action - requires user permission"""
    action_id: str
    problem: str
    proposal: str
    command_preview: Optional[str]  # What will run (for transparency)
    reversible: bool
    risk: RecoveryRisk
    
    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "problem": self.problem,
            "proposal": self.proposal,
            "command_preview": self.command_preview,
            "reversible": self.reversible,
            "risk": self.risk.value,
            "requires_permission": True  # ALWAYS TRUE
        }


# ============================================================================
# Error Explanations (Phase 1)
# ============================================================================

ERROR_EXPLANATIONS = {
    # Network/Connection errors
    "connection refused": {
        "cause": "The service isn't running",
        "fix": "Start the required service",
    },
    "connectionrefusederror": {
        "cause": "Cannot connect to the service",
        "fix": "Check if the service is running",
    },
    "timeout": {
        "cause": "The service is taking too long to respond",
        "fix": "The service might be overloaded or stuck",
    },
    
    # CUDA/GPU errors
    "cuda out of memory": {
        "cause": "GPU memory is full",
        "fix": "Close other GPU applications or use a smaller model",
    },
    "cuda": {
        "cause": "GPU/CUDA issue detected",
        "fix": "Check your GPU drivers or try CPU mode",
    },
    
    # Audio errors
    "no audio devices": {
        "cause": "No microphone or speaker detected",
        "fix": "Check your audio device connections",
    },
    "portaudio": {
        "cause": "Audio system error",
        "fix": "Check your audio devices and drivers",
    },
    "audio device": {
        "cause": "Audio device issue",
        "fix": "Reconnect your audio device or select a different one",
    },
    
    # Model errors
    "model not found": {
        "cause": "The neural network model isn't downloaded",
        "fix": "Download the model with: ollama pull <model>",
    },
    "file not found": {
        "cause": "A required file is missing",
        "fix": "Check installation or reinstall the component",
    },
    
    # Ollama specific
    "ollama": {
        "cause": "Ollama neural network issue",
        "fix": "Check if Ollama is running: ollama serve",
    },
    
    # Whisper/STT
    "whisper": {
        "cause": "Speech recognition issue",
        "fix": "Check Whisper installation",
    },
    
    # Piper/TTS
    "piper": {
        "cause": "Voice synthesis issue", 
        "fix": "Check Piper installation and voice model",
    },
}


def explain_error(error_message: str) -> dict:
    """
    Convert a cryptic error into a human-readable explanation.
    Returns {"cause": "...", "fix": "..."} or None if unknown.
    """
    error_lower = error_message.lower()
    
    for pattern, explanation in ERROR_EXPLANATIONS.items():
        if pattern in error_lower:
            return explanation
    
    return {
        "cause": "An unexpected error occurred",
        "fix": "Check the logs for more details",
    }


# ============================================================================
# Component Health Checks (Phase 1)
# ============================================================================

class SystemDiagnostics:
    """
    Diagnose the health of all ARGO components.
    Read-only - does not fix anything.
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.last_check: dict = {}
        self.last_check_time: float = 0
    
    def check_all(self) -> dict[str, ComponentHealth]:
        """Run all health checks and return results"""
        results = {}
        
        # Run checks
        results["ollama"] = self._check_ollama()
        results["piper"] = self._check_piper()
        results["whisper"] = self._check_whisper()
        results["audio_input"] = self._check_audio_input()
        results["audio_output"] = self._check_audio_output()
        results["disk_space"] = self._check_disk_space()
        results["memory"] = self._check_memory()
        
        self.last_check = results
        self.last_check_time = time.time()
        
        return results
    
    def get_summary(self) -> dict:
        """Get a summary of system health"""
        if not self.last_check:
            self.check_all()
        
        errors = []
        warnings = []
        ok_count = 0
        
        for name, health in self.last_check.items():
            if health.status == HealthStatus.ERROR:
                errors.append(health)
            elif health.status == HealthStatus.WARNING:
                warnings.append(health)
            elif health.status == HealthStatus.OK:
                ok_count += 1
        
        if errors:
            overall = HealthStatus.ERROR
            summary = f"{len(errors)} component(s) have errors"
        elif warnings:
            overall = HealthStatus.WARNING
            summary = f"{len(warnings)} warning(s), {ok_count} OK"
        else:
            overall = HealthStatus.OK
            summary = f"All {ok_count} components healthy"
        
        return {
            "overall": overall.value,
            "summary": summary,
            "errors": [{"name": e.name, "message": e.message, "fix": e.suggested_fix} for e in errors],
            "warnings": [{"name": w.name, "message": w.message} for w in warnings],
            "ok_count": ok_count,
            "checked_at": self.last_check_time,
        }
    
    def _check_ollama(self) -> ComponentHealth:
        """Check if Ollama is running and responding"""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "unknown") for m in data.get("models", [])]
                return ComponentHealth(
                    name="ollama",
                    status=HealthStatus.OK,
                    message="Ollama is running",
                    details={"models": models},
                )
            else:
                return ComponentHealth(
                    name="ollama",
                    status=HealthStatus.ERROR,
                    message=f"Ollama returned status {response.status_code}",
                    suggested_fix="Restart Ollama",
                    recovery_action="restart_ollama",
                )
        except requests.exceptions.ConnectionError:
            return ComponentHealth(
                name="ollama",
                status=HealthStatus.ERROR,
                message="Ollama is not running",
                suggested_fix="Start Ollama with: ollama serve",
                recovery_action="start_ollama",
            )
        except requests.exceptions.Timeout:
            return ComponentHealth(
                name="ollama",
                status=HealthStatus.WARNING,
                message="Ollama is slow to respond",
                suggested_fix="Ollama might be loading a model",
            )
        except Exception as e:
            return ComponentHealth(
                name="ollama",
                status=HealthStatus.ERROR,
                message=f"Ollama check failed: {e}",
                suggested_fix="Check Ollama installation",
            )
    
    def _check_piper(self) -> ComponentHealth:
        """Check if Piper TTS is available"""
        # Check for piper binary
        piper_paths = [
            Path("piper/piper.exe"),
            Path("piper/piper"),
            Path("/usr/local/bin/piper"),
        ]
        
        piper_found = None
        for p in piper_paths:
            if p.exists():
                piper_found = p
                break
        
        if not piper_found:
            # Try finding in PATH
            try:
                result = subprocess.run(
                    ["where" if os.name == "nt" else "which", "piper"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    piper_found = Path(result.stdout.strip().split("\n")[0])
            except Exception:
                pass
        
        if not piper_found:
            return ComponentHealth(
                name="piper",
                status=HealthStatus.ERROR,
                message="Piper TTS not found",
                suggested_fix="Install Piper or check piper/ directory",
            )
        
        # Check for voice model
        voice_paths = [
            Path("voices"),
            Path("piper/voices"),
        ]
        
        voices_found = []
        for vp in voice_paths:
            if vp.exists():
                voices_found = list(vp.glob("*.onnx"))
                break
        
        if not voices_found:
            return ComponentHealth(
                name="piper",
                status=HealthStatus.WARNING,
                message="Piper found but no voice models",
                details={"piper_path": str(piper_found)},
                suggested_fix="Download a voice model to voices/",
            )
        
        return ComponentHealth(
            name="piper",
            status=HealthStatus.OK,
            message=f"Piper ready with {len(voices_found)} voice(s)",
            details={"piper_path": str(piper_found), "voices": len(voices_found)},
        )
    
    def _check_whisper(self) -> ComponentHealth:
        """Check if Whisper STT is available"""
        try:
            import whisper  # noqa: F401
            return ComponentHealth(
                name="whisper",
                status=HealthStatus.OK,
                message="Whisper is available",
            )
        except ImportError:
            return ComponentHealth(
                name="whisper",
                status=HealthStatus.ERROR,
                message="Whisper not installed",
                suggested_fix="Install with: pip install openai-whisper",
            )
        except Exception as e:
            return ComponentHealth(
                name="whisper",
                status=HealthStatus.WARNING,
                message=f"Whisper import warning: {e}",
            )
    
    def _check_audio_input(self) -> ComponentHealth:
        """Check microphone availability"""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
            
            if not inputs:
                return ComponentHealth(
                    name="audio_input",
                    status=HealthStatus.ERROR,
                    message="No microphone found",
                    suggested_fix="Connect a microphone",
                )
            
            default = sd.query_devices(kind="input")
            return ComponentHealth(
                name="audio_input",
                status=HealthStatus.OK,
                message=f"Microphone ready: {default.get('name', 'Unknown')}",
                details={"device": default.get("name"), "available": len(inputs)},
            )
        except Exception as e:
            return ComponentHealth(
                name="audio_input",
                status=HealthStatus.ERROR,
                message=f"Audio input check failed: {e}",
                suggested_fix="Check audio drivers",
                recovery_action="reinit_audio",
            )
    
    def _check_audio_output(self) -> ComponentHealth:
        """Check speaker availability"""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            outputs = [d for d in devices if d.get("max_output_channels", 0) > 0]
            
            if not outputs:
                return ComponentHealth(
                    name="audio_output",
                    status=HealthStatus.ERROR,
                    message="No speaker/output found",
                    suggested_fix="Connect an audio output device",
                )
            
            default = sd.query_devices(kind="output")
            return ComponentHealth(
                name="audio_output",
                status=HealthStatus.OK,
                message=f"Speaker ready: {default.get('name', 'Unknown')}",
                details={"device": default.get("name"), "available": len(outputs)},
            )
        except Exception as e:
            return ComponentHealth(
                name="audio_output",
                status=HealthStatus.ERROR,
                message=f"Audio output check failed: {e}",
                suggested_fix="Check audio drivers",
                recovery_action="reinit_audio",
            )
    
    def _check_disk_space(self) -> ComponentHealth:
        """Check available disk space"""
        try:
            usage = psutil.disk_usage(os.getcwd())
            free_gb = usage.free / (1024**3)
            percent_used = usage.percent
            
            if free_gb < 1:
                return ComponentHealth(
                    name="disk_space",
                    status=HealthStatus.ERROR,
                    message=f"Very low disk space: {free_gb:.1f} GB free",
                    suggested_fix="Free up disk space",
                )
            elif free_gb < 5:
                return ComponentHealth(
                    name="disk_space",
                    status=HealthStatus.WARNING,
                    message=f"Low disk space: {free_gb:.1f} GB free",
                )
            else:
                return ComponentHealth(
                    name="disk_space",
                    status=HealthStatus.OK,
                    message=f"{free_gb:.1f} GB free ({100-percent_used:.0f}% available)",
                )
        except Exception as e:
            return ComponentHealth(
                name="disk_space",
                status=HealthStatus.UNKNOWN,
                message=f"Could not check disk: {e}",
            )
    
    def _check_memory(self) -> ComponentHealth:
        """Check available RAM"""
        try:
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)
            percent_used = mem.percent
            
            if percent_used > 95:
                return ComponentHealth(
                    name="memory",
                    status=HealthStatus.ERROR,
                    message=f"Critical memory pressure: {percent_used:.0f}% used",
                    suggested_fix="Close other applications",
                )
            elif percent_used > 85:
                return ComponentHealth(
                    name="memory",
                    status=HealthStatus.WARNING,
                    message=f"High memory usage: {percent_used:.0f}% ({available_gb:.1f} GB free)",
                )
            else:
                return ComponentHealth(
                    name="memory",
                    status=HealthStatus.OK,
                    message=f"{available_gb:.1f} GB available ({percent_used:.0f}% used)",
                )
        except Exception as e:
            return ComponentHealth(
                name="memory",
                status=HealthStatus.UNKNOWN,
                message=f"Could not check memory: {e}",
            )


# ============================================================================
# Assisted Recovery (Phase 2)
# ============================================================================

class AssistedRecovery:
    """
    Propose and execute recovery actions WITH USER PERMISSION.
    
    CRITICAL: No action executes without explicit approval.
    """
    
    # Allowed actions - exhaustive list
    ALLOWED_ACTIONS = {
        "restart_stt": {
            "description": "Restart speech recognition engine",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "restart_tts": {
            "description": "Restart voice synthesis engine",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "start_ollama": {
            "description": "Start Ollama service",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "restart_ollama": {
            "description": "Restart Ollama service",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "reinit_audio": {
            "description": "Reinitialize audio devices",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "retry_last": {
            "description": "Retry the last failed operation",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "clear_audio_buffer": {
            "description": "Clear stuck audio buffer",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
        "reset_state": {
            "description": "Reset to IDLE state",
            "risk": RecoveryRisk.LOW,
            "reversible": True,
        },
    }
    
    def __init__(self, pipeline=None, broadcast_fn: Callable = None):
        self.pipeline = pipeline
        self.broadcast = broadcast_fn or (lambda *args: None)
        self.pending_proposals: dict[str, RecoveryProposal] = {}
        self.action_log: list[dict] = []
    
    def propose(self, action_id: str, problem: str) -> Optional[RecoveryProposal]:
        """
        Create a recovery proposal. Does NOT execute.
        Returns the proposal for UI display.
        """
        if action_id not in self.ALLOWED_ACTIONS:
            logger.warning(f"Attempted to propose forbidden action: {action_id}")
            return None
        
        action_info = self.ALLOWED_ACTIONS[action_id]
        
        proposal = RecoveryProposal(
            action_id=action_id,
            problem=problem,
            proposal=action_info["description"],
            command_preview=self._get_command_preview(action_id),
            reversible=action_info["reversible"],
            risk=action_info["risk"],
        )
        
        self.pending_proposals[action_id] = proposal
        
        # Broadcast to UI for permission prompt
        self.broadcast("recovery_proposal", proposal.to_dict())
        
        logger.info(f"Recovery proposed: {action_id} for '{problem}'")
        return proposal
    
    def _get_command_preview(self, action_id: str) -> str:
        """Show what the action will do (transparency)"""
        previews = {
            "start_ollama": "subprocess: ollama serve",
            "restart_ollama": "taskkill ollama + ollama serve",
            "restart_stt": "pipeline.stt_engine = None; reinit",
            "restart_tts": "output_sink.cleanup(); reinit",
            "reinit_audio": "sounddevice.default.reset()",
            "retry_last": "re-execute last pipeline step",
            "clear_audio_buffer": "audio_buffer.clear()",
            "reset_state": "state_machine.force_transition(IDLE)",
        }
        return previews.get(action_id, "internal operation")
    
    async def execute_if_approved(self, action_id: str, approved: bool) -> dict:
        """
        Execute action ONLY if user approved.
        Returns result for UI feedback.
        """
        # Log the decision regardless
        log_entry = {
            "action_id": action_id,
            "approved": approved,
            "timestamp": time.time(),
        }
        
        if not approved:
            log_entry["result"] = "cancelled"
            log_entry["message"] = "User declined"
            self.action_log.append(log_entry)
            self.pending_proposals.pop(action_id, None)
            logger.info(f"Recovery declined by user: {action_id}")
            return {"status": "cancelled", "message": "User declined recovery action"}
        
        if action_id not in self.ALLOWED_ACTIONS:
            log_entry["result"] = "rejected"
            log_entry["message"] = "Action not allowed"
            self.action_log.append(log_entry)
            logger.error(f"Attempted to execute forbidden action: {action_id}")
            return {"status": "error", "message": "Action not in allowed list"}
        
        # Execute the approved action
        try:
            result = await self._execute_action(action_id)
            log_entry["result"] = "success"
            log_entry["message"] = result.get("message", "Completed")
            self.action_log.append(log_entry)
            self.pending_proposals.pop(action_id, None)
            
            # Broadcast success
            self.broadcast("recovery_result", {
                "action_id": action_id,
                "status": "success",
                "message": result.get("message"),
            })
            
            logger.info(f"Recovery executed successfully: {action_id}")
            return result
            
        except Exception as e:
            log_entry["result"] = "failed"
            log_entry["message"] = str(e)
            self.action_log.append(log_entry)
            
            self.broadcast("recovery_result", {
                "action_id": action_id,
                "status": "failed",
                "message": str(e),
            })
            
            logger.error(f"Recovery action failed: {action_id} - {e}")
            return {"status": "error", "message": str(e)}
    
    async def _execute_action(self, action_id: str) -> dict:
        """Internal: execute an approved action"""
        
        if action_id == "start_ollama":
            return await self._start_ollama()
        
        elif action_id == "restart_ollama":
            return await self._restart_ollama()
        
        elif action_id == "restart_stt":
            return await self._restart_stt()
        
        elif action_id == "restart_tts":
            return await self._restart_tts()
        
        elif action_id == "reinit_audio":
            return await self._reinit_audio()
        
        elif action_id == "reset_state":
            return await self._reset_state()
        
        elif action_id == "clear_audio_buffer":
            return await self._clear_audio_buffer()
        
        elif action_id == "retry_last":
            return {"status": "success", "message": "Retry triggered"}
        
        else:
            return {"status": "error", "message": f"Unknown action: {action_id}"}
    
    # --- Individual recovery actions ---
    
    async def _start_ollama(self) -> dict:
        """Start Ollama service"""
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            
            # Wait for startup
            await asyncio.sleep(3)
            
            # Verify
            try:
                requests.get("http://localhost:11434/api/tags", timeout=5)
                return {"status": "success", "message": "Ollama started successfully"}
            except Exception:
                return {"status": "warning", "message": "Ollama started but not yet responding"}
            
        except FileNotFoundError:
            return {"status": "error", "message": "Ollama not found in PATH"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to start Ollama: {e}"}
    
    async def _restart_ollama(self) -> dict:
        """Restart Ollama service"""
        try:
            # Kill existing
            if os.name == "nt":
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], 
                             capture_output=True, timeout=5)
            else:
                subprocess.run(["pkill", "-f", "ollama"], 
                             capture_output=True, timeout=5)
            
            await asyncio.sleep(1)
            
            # Start fresh
            return await self._start_ollama()
            
        except Exception as e:
            return {"status": "error", "message": f"Failed to restart Ollama: {e}"}
    
    async def _restart_stt(self) -> dict:
        """Restart speech recognition"""
        if not self.pipeline:
            return {"status": "error", "message": "No pipeline reference"}
        
        try:
            # Release current
            if hasattr(self.pipeline, 'stt_engine'):
                self.pipeline.stt_engine = None
            
            await asyncio.sleep(0.5)
            
            # Reinitialize
            if hasattr(self.pipeline, '_init_stt_engine'):
                self.pipeline._init_stt_engine()
            
            return {"status": "success", "message": "Speech recognition restarted"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to restart STT: {e}"}
    
    async def _restart_tts(self) -> dict:
        """Restart voice synthesis"""
        if not self.pipeline:
            return {"status": "error", "message": "No pipeline reference"}
        
        try:
            # Cleanup current
            if hasattr(self.pipeline, 'output_sink'):
                if hasattr(self.pipeline.output_sink, 'cleanup'):
                    await self.pipeline.output_sink.cleanup()
            
            await asyncio.sleep(0.5)
            
            # Reinitialize
            if hasattr(self.pipeline, '_init_tts'):
                await self.pipeline._init_tts()
            
            return {"status": "success", "message": "Voice synthesis restarted"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to restart TTS: {e}"}
    
    async def _reinit_audio(self) -> dict:
        """Reinitialize audio devices"""
        try:
            import sounddevice as sd
            sd.default.reset()
            
            # Query devices to refresh
            sd.query_devices()
            
            return {"status": "success", "message": "Audio devices reinitialized"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to reinit audio: {e}"}
    
    async def _reset_state(self) -> dict:
        """Reset state machine to IDLE"""
        if not self.pipeline:
            return {"status": "error", "message": "No pipeline reference"}
        
        try:
            if hasattr(self.pipeline, 'state_machine'):
                self.pipeline.state_machine.force_state("IDLE")
            elif hasattr(self.pipeline, 'current_state'):
                self.pipeline.current_state = "IDLE"
            
            self.broadcast("status", "IDLE")
            
            return {"status": "success", "message": "State reset to IDLE"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to reset state: {e}"}
    
    async def _clear_audio_buffer(self) -> dict:
        """Clear any stuck audio"""
        if not self.pipeline:
            return {"status": "error", "message": "No pipeline reference"}
        
        try:
            if hasattr(self.pipeline, 'audio_buffer'):
                self.pipeline.audio_buffer.clear()
            
            return {"status": "success", "message": "Audio buffer cleared"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to clear buffer: {e}"}


# ============================================================================
# Convenience Functions
# ============================================================================

def run_diagnostics() -> dict:
    """Quick health check - returns summary"""
    diag = SystemDiagnostics()
    diag.check_all()
    return diag.get_summary()


def get_human_readable_error(error: str) -> str:
    """Convert error to human-readable explanation"""
    explanation = explain_error(error)
    return f"{explanation['cause']}. {explanation['fix']}"


# ============================================================================
# Test
# ============================================================================

if __name__ == "__main__":
    print("Running ARGO Self-Diagnostics...")
    print("=" * 50)
    
    result = run_diagnostics()
    
    print(f"\nOverall: {result['overall'].upper()}")
    print(f"Summary: {result['summary']}")
    
    if result['errors']:
        print("\n❌ Errors:")
        for e in result['errors']:
            print(f"  - {e['name']}: {e['message']}")
            if e.get('fix'):
                print(f"    Fix: {e['fix']}")
    
    if result['warnings']:
        print("\n⚠️ Warnings:")
        for w in result['warnings']:
            print(f"  - {w['name']}: {w['message']}")
    
    print(f"\n✅ {result['ok_count']} component(s) healthy")
