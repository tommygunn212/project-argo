
# ============================================================================
# 1) IMPORTS
# ============================================================================
import asyncio
import faulthandler
import websockets
import json
import threading
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# 2) PATH SETUP / ENV
# ============================================================================
# Add core to path just in case
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(repo_root)

# Load environment variables from .env (ignored by git)
load_dotenv(Path(repo_root) / ".env")

# Enable native crash logging (access violations, etc.)
try:
    logs_dir = os.path.join(repo_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    crash_log_path = os.path.join(logs_dir, "native_crash.log")
    _faulthandler_file = open(crash_log_path, "a", buffering=1)
    _faulthandler_file.write("\n" + "=" * 80 + "\n")
    _faulthandler_file.write(f"NATIVE CRASH LOG START: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _faulthandler_file.write("=" * 80 + "\n")
    faulthandler.enable(file=_faulthandler_file, all_threads=True)
except Exception:
    pass

 

# ============================================================================
# 3) CORE IMPORTS
# ============================================================================
from core.audio_manager import AudioManager, INPUT_SAMPLE_RATE, BLOCK_SIZE
from core.pipeline import ArgoPipeline
from core.database import get_db_status
from core.config import MUSIC_DB_PATH
from core.classic_runtime_startup import start_classic_runtime
from core.classic_capture_loop import run_classic_capture_loop
from core.classic_main_runtime import ClassicMainRuntime, run_classic_main_runtime
from core.frontend_text_input import FrontendTextDependencies, dispatch_frontend_text
from core.frontend_websocket import (
    FrontendWebSocketDependencies,
    serve_frontend_websocket,
)
from core.frontend_overrides import (
    FrontendOverrideDependencies,
    dispatch_frontend_override,
)
from core.frontend_diagnostics import (
    FrontendDiagnosticsDependencies,
    dispatch_frontend_diagnostics,
)
from core.frontend_interrupt import (
    FrontendInterruptDependencies,
    interrupt_current_response,
)
from core.backend_control import BackendControlRuntime, dispatch_backend_control
from core.noise_calibration import calibrate_ambient_noise
from core.self_diagnostics import SystemDiagnostics, AssistedRecovery, explain_error
from core.code_repair import CodeRepairManager
from core.repair_service import RepairService, ActiveDiagnostics
from core.frontend_http import build_frontend_handler
from core.instrumentation import log_event
from core.sound_cues import get_sound_cue_player
from system_profile import get_system_profile, get_gpu_profile
from core.version import CURRENT_VERSION, CURRENT_MILESTONE
from core.config import (
    get_config,
    get_config_hash,
    get_runtime_overrides,
    set_runtime_override,
    set_runtime_overrides,
    clear_runtime_overrides,
)

# ============================================================================
# 4) GLOBALS / RUNTIME STATE
# ============================================================================
# Thread-safe event loop reference BEFORE logging setup
ui_loop = None
connected_clients = set()
CURRENT_STATUS = "INITIALIZING"  # Stores the latest state to sync new clients
pipeline_ref = None
audio_ref = None
_noise_calibrate_fn = None  # Set by main loop; callable from control handler
LISTENING_ENABLED = False
SERVER_ENABLED = True
main_loop_thread = None

# ---------------------------------------------------------------------------
# Microphone ownership
# ---------------------------------------------------------------------------
# Smooth Voice (LiveKit) and the classic STT/TTS pipeline must never hold the
# microphone at the same time. Two open mics in one room is how ARGO ends up
# hearing its own speakers: barge-in trips on its own voice and Whisper
# invents words out of the tail.
#
# This is deliberately a MODE and not a liveness check. While Smooth Voice is
# selected it owns the microphone even when LiveKit is disconnected, the
# worker is dead, the browser is reconnecting, or a second tab is open. Only
# an explicit switch back to classic releases it. The mode is persisted so a
# server restart does not quietly hand the microphone back either.
VOICE_MODE_SMOOTH = "smooth"
VOICE_MODE_CLASSIC = "classic"
VOICE_MODE_FILE = Path(__file__).resolve().parent / "runtime" / "voice_mode.json"
VOICE_MODE = VOICE_MODE_CLASSIC

# Phases the browser reports while it holds a LiveKit microphone.
SMOOTH_VOICE_LIVE_PHASES = {
    "live", "livekit_client_ready", "mic_acquired", "connecting",
    "remote_audio_subscribed",
}


def _load_voice_mode() -> str:
    """Read the persisted mode. A missing or damaged file means classic."""
    try:
        raw = json.loads(VOICE_MODE_FILE.read_text(encoding="utf-8"))
        mode = str(raw.get("mode", "")).strip().lower()
        if mode in (VOICE_MODE_SMOOTH, VOICE_MODE_CLASSIC):
            return mode
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("[VoiceMode] unreadable %s; defaulting to classic", VOICE_MODE_FILE)
    return VOICE_MODE_CLASSIC


def _save_voice_mode(mode: str) -> None:
    try:
        VOICE_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = VOICE_MODE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"mode": mode}, indent=2), encoding="utf-8")
        tmp.replace(VOICE_MODE_FILE)
    except Exception:
        logger.warning("[VoiceMode] could not persist mode", exc_info=True)


def _set_voice_mode(mode: str, reason: str) -> None:
    """Change who owns the microphone, and stop the other path immediately."""
    global VOICE_MODE, LISTENING_ENABLED
    mode = mode if mode in (VOICE_MODE_SMOOTH, VOICE_MODE_CLASSIC) else VOICE_MODE_CLASSIC
    changed = mode != VOICE_MODE
    VOICE_MODE = mode
    _save_voice_mode(mode)
    if changed:
        logger.info("[VoiceMode] %s owns the microphone (%s)", mode, reason)
        broadcast_msg("voice_mode", {"mode": mode, "reason": reason})
    if mode == VOICE_MODE_SMOOTH and LISTENING_ENABLED:
        logger.warning("[VoiceMode] classic listener was running; stopping it")
        LISTENING_ENABLED = False
        if audio_ref:
            try:
                audio_ref.stop()
            except Exception:
                logger.debug("[VoiceMode] could not stop classic audio", exc_info=True)


def _note_smooth_voice_phase(phase: str) -> None:
    """Claim the microphone for Smooth Voice from the browser's own phases.

    Only claims. Nothing the browser reports ever RELEASES the microphone -
    not "disconnected", not "error", not a closed tab. Releasing is an
    explicit user action, handled in the control path.
    """
    if (phase or "").strip().lower() in SMOOTH_VOICE_LIVE_PHASES:
        _set_voice_mode(VOICE_MODE_SMOOTH, f"smooth voice phase: {phase}")

# Self-diagnostics and assisted recovery (Phase 1 & 2)
diagnostics_ref = None
recovery_ref = None
code_repair_ref = None
repair_service_ref = None
repair_bridge_token = None

# ============================================================================
# 5) LOGGING
# ============================================================================
# Custom logging handler to broadcast logs via WebSocket

def _env_enabled(name: str, default: bool = False) -> bool:
    """True when an ARGO feature flag is switched on in the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            # Use the helper to ensure thread safety, but avoid circular logic if possible
            if ui_loop and ui_loop.is_running():
                payload = json.dumps({"type": "log", "payload": msg})
                asyncio.run_coroutine_threadsafe(send_to_clients(payload), ui_loop)
        except Exception:
            self.handleError(record)

# Setup logging - ATTACH TO ROOT LOGGER so we catch Pipeline/Audio logs too
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
root_logger = logging.getLogger()
ws_handler = WebSocketLogHandler()
ws_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
root_logger.addHandler(ws_handler)

logger = logging.getLogger("ARGO.Main")

HTTP_HOST = os.getenv("ARGO_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("ARGO_HTTP_PORT", "8000"))
WS_HOST = os.getenv("ARGO_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("ARGO_WS_PORT", "8001"))

# ============================================================================
# 6) VERSION / PROFILE INIT
# ============================================================================
logger.info("[SYSTEM] ARGO version %s (%s)", CURRENT_VERSION, CURRENT_MILESTONE)

# Load static system profile once
SYSTEM_PROFILE = get_system_profile()
GPU_PROFILE = get_gpu_profile()
logger.info("[SYSTEM] Hardware profile loaded")

# ============================================================================
# 7) CONFIG LOAD
# ============================================================================
# Hardware Config
config = get_config()
sound_cues = get_sound_cue_player(config)
AUDIO_INPUT_INDEX = config.get("audio.input_device_index")
AUDIO_OUTPUT_INDEX = config.get("audio.output_device_index")

# Runtime control
RUNTIME_OVERRIDES = get_runtime_overrides()
NEXT_INTERACTION_OVERRIDES = {}

# Optional env overrides (non-persistent)
barge_env = os.getenv("ARGO_BARGE_IN_ENABLED")
if barge_env is not None:
    RUNTIME_OVERRIDES["barge_in_enabled"] = barge_env.strip().lower() in ("1", "true", "yes", "on")

# Start in always-listening mode unless explicitly disabled
LISTENING_ENABLED = bool(config.get("audio.always_listen", True))

def broadcast_msg(msg_type, data):
    """Bridge between Sync Backend and Async UI."""
    global CURRENT_STATUS
    
    # Update state memory
    if msg_type == "status":
        CURRENT_STATUS = data
        
    if ui_loop and ui_loop.is_running():
        msg = json.dumps({"type": msg_type, "payload": data})
        asyncio.run_coroutine_threadsafe(send_to_clients(msg), ui_loop)


def _set_listening_enabled(enabled: bool) -> None:
    global LISTENING_ENABLED
    LISTENING_ENABLED = bool(enabled)


def _build_frontend_handler():
    return build_frontend_handler({
        "repo_root": repo_root,
        "http_port": HTTP_PORT,
        "ws_port": WS_PORT,
        "logger": logger,
        "get_config": get_config,
        "env_enabled": _env_enabled,
        "handle_control": _handle_control,
        "hard_reset_pipeline": _hard_reset_pipeline,
        "broadcast_msg": broadcast_msg,
        "note_smooth_voice_phase": _note_smooth_voice_phase,
        "set_listening_enabled": _set_listening_enabled,
        "get_current_status": lambda: CURRENT_STATUS,
        "get_repair_bridge_token": lambda: repair_bridge_token,
        "get_repair_service": lambda: repair_service_ref,
    })

async def send_to_clients(msg):
    if not connected_clients:
        return
    for ws in list(connected_clients):
        try:
            await ws.send(msg)
        except Exception as e:
            logger.error(f"[Main] Failed to send to client: {e}")
            connected_clients.discard(ws)

async def websocket_handler(websocket):
    await serve_frontend_websocket(
        websocket,
        FrontendWebSocketDependencies(
            connected_clients=connected_clients,
            get_current_status=lambda: CURRENT_STATUS,
            get_config_hash=get_config_hash,
            get_runtime_overrides=get_runtime_overrides,
            get_database_status=lambda: get_db_status(MUSIC_DB_PATH),
            get_pipeline=lambda: pipeline_ref,
            get_code_repair=lambda: code_repair_ref,
            handle_text_input=_handle_text_input,
            handle_diagnostics=_handle_diagnostics,
            handle_recovery_response=_handle_recovery_response,
            handle_code_repair_request=_handle_code_repair_request,
            handle_code_repair_response=_handle_code_repair_response,
            handle_control=_handle_control,
            handle_override=_handle_override,
            handle_next_override=_handle_next_override,
            handle_clear_overrides=_handle_clear_overrides,
            broadcast=broadcast_msg,
            thread_factory=threading.Thread,
        ),
    )


def _run_noise_calibration():
    """Called from control handler to trigger recalibration."""
    if _noise_calibrate_fn:
        _noise_calibrate_fn()
    else:
        logger.warning("[CALIBRATE] Calibration function not available yet")
        broadcast_msg("log", "Calibration not available — main loop not running")


def _interrupt_current_response(reason: str, target_state: str = "LISTENING", clear_buffers: bool = True):
    """Shared UI/audio interrupt path for barge-in, stop, restart, and reset."""
    interrupt_current_response(
        FrontendInterruptDependencies(
            get_pipeline=lambda: pipeline_ref,
            get_audio=lambda: audio_ref,
            stop_active_cue=sound_cues.stop_active_cue,
            logger=logger,
        ),
        reason,
        target_state=target_state,
        clear_buffers=clear_buffers,
    )


def _hard_reset_pipeline(reason: str) -> dict:
    """Break a wedged turn. Never raises; always reports what it managed."""
    if not (pipeline_ref and hasattr(pipeline_ref, "hard_reset")):
        return {"ok": False, "error": "pipeline not running"}
    try:
        result = pipeline_ref.hard_reset(reason)
        if result.get("processing_lock_broken"):
            broadcast_msg("log", "Broke a stuck turn that was blocking new input")
        return result
    except Exception as exc:
        logger.exception("[CONTROL] hard reset failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _handle_control(command):
    def set_listening(enabled: bool) -> None:
        global LISTENING_ENABLED
        LISTENING_ENABLED = enabled

    def set_server(enabled: bool) -> None:
        global SERVER_ENABLED
        SERVER_ENABLED = enabled

    dispatch_backend_control(
        BackendControlRuntime(
            smooth_voice_mode=VOICE_MODE_SMOOTH,
            classic_voice_mode=VOICE_MODE_CLASSIC,
            get_voice_mode=lambda: VOICE_MODE,
            set_voice_mode=_set_voice_mode,
            set_listening_enabled=set_listening,
            set_server_enabled=set_server,
            get_pipeline=lambda: pipeline_ref,
            get_audio=lambda: audio_ref,
            get_main_loop_thread=lambda: main_loop_thread,
            start_main_loop_thread=_start_main_loop_thread,
            interrupt_current_response=_interrupt_current_response,
            hard_reset_pipeline=_hard_reset_pipeline,
            run_noise_calibration=_run_noise_calibration,
            clear_overrides=_handle_clear_overrides,
            next_interaction_overrides=NEXT_INTERACTION_OVERRIDES,
            broadcast=broadcast_msg,
            event_logger=log_event,
            logger=logger,
        ),
        command,
    )


def _handle_override(payload: dict):
    dispatch_frontend_override(
        FrontendOverrideDependencies(
            set_runtime_override=set_runtime_override,
            get_runtime_overrides=get_runtime_overrides,
            get_pipeline=lambda: pipeline_ref,
            set_root_log_level=logging.getLogger().setLevel,
            log_event=log_event,
            broadcast=broadcast_msg,
            logger=logger,
        ),
        payload,
    )


def _handle_next_override(payload: dict):
    key = payload.get("key")
    value = payload.get("value")
    if not key:
        return
    NEXT_INTERACTION_OVERRIDES[key] = value
    log_event(f"UI_CMD_NEXT_OVERRIDE {key}={value}", stage="ui")


def _handle_clear_overrides():
    clear_runtime_overrides()
    log_event("UI_CMD_CLEAR_OVERRIDES", stage="ui")
    broadcast_msg("runtime_overrides", get_runtime_overrides())


def _handle_text_input(payload: dict | str):
    """Route frontend text through the classic conversation pipeline."""
    if not pipeline_ref:
        logger.warning("[TEXT_INPUT] No pipeline available")
        return
    dispatch_frontend_text(
        FrontendTextDependencies(
            logger=logger,
            get_current_state=lambda: getattr(pipeline_ref, "current_state", "IDLE"),
            interrupt_current_response=_interrupt_current_response,
            transition_state=pipeline_ref.transition_state,
            normalize_music_text=pipeline_ref._normalize_music_command_text,
            broadcast=pipeline_ref.broadcast,
            add_conversation_turn=pipeline_ref._conversation_buffer.add,
            broadcast_turn_info=pipeline_ref._broadcast_turn_info,
            append_conversation_ledger=pipeline_ref._append_convo_ledger,
            handle_user_text=pipeline_ref.handle_user_text,
            read_next_overrides=lambda: (
                dict(NEXT_INTERACTION_OVERRIDES)
                if NEXT_INTERACTION_OVERRIDES
                else None
            ),
            clear_next_overrides=NEXT_INTERACTION_OVERRIDES.clear,
            log_event=log_event,
            new_interaction_id=lambda: str(uuid.uuid4()),
            thread_factory=threading.Thread,
        ),
        payload,
    )


# ============================================================================
# PHASE 1 & 2: Self-Diagnostics and Assisted Recovery
# ============================================================================

async def _handle_diagnostics(websocket):
    """Run diagnostics and send results to requesting client.
    
    Phase 1: Detect and explain problems.
    """
    def set_diagnostics(value) -> None:
        global diagnostics_ref
        diagnostics_ref = value

    await dispatch_frontend_diagnostics(
        FrontendDiagnosticsDependencies(
            get_repair_service=lambda: repair_service_ref,
            get_diagnostics=lambda: diagnostics_ref,
            set_diagnostics=set_diagnostics,
            diagnostics_factory=SystemDiagnostics,
            get_recovery=lambda: recovery_ref,
            broadcast=broadcast_msg,
            log_event=log_event,
            logger=logger,
        ),
        websocket,
    )


async def _handle_recovery_response(payload: dict):
    """Handle user's response to a recovery proposal.
    
    Phase 2: Execute recovery ONLY if user approved.
    
    Payload:
      {"proposal_id": "unique-id-from-proposal", "approved": true}
    """
    if not isinstance(payload, dict) or not repair_service_ref:
        return
    result = await asyncio.to_thread(repair_service_ref.respond,
        payload.get("proposal_id", ""), payload.get("approved"))
    if pipeline_ref and LISTENING_ENABLED and result.get("message"):
        # The server loop stays responsive while classic TTS speaks the result.
        await asyncio.to_thread(pipeline_ref.speak, result["message"])


def _init_recovery_system():
    """Initialize assisted recovery system with pipeline reference."""
    global recovery_ref, diagnostics_ref, code_repair_ref, repair_service_ref, repair_bridge_token
    
    diagnostics_ref = SystemDiagnostics()
    recovery_ref = AssistedRecovery(
        pipeline=pipeline_ref,
        broadcast_fn=broadcast_msg
    )
    if pipeline_ref is not None:
        pipeline_ref.recovery_manager = recovery_ref
    code_repair_ref = CodeRepairManager(broadcast_fn=broadcast_msg)
    repair_service_ref = RepairService(recovery_ref, code_repair_ref, broadcast_msg,
        diagnostics_factory=lambda: ActiveDiagnostics(pipeline_ref))
    if pipeline_ref is not None:
        pipeline_ref.repair_service = repair_service_ref
    import secrets
    repair_bridge_token = secrets.token_urlsafe(32)
    token_path = Path(repo_root) / "runtime" / "repair_bridge.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(repair_bridge_token, encoding="utf-8")
    logger.info("[RECOVERY] Assisted recovery system initialized")


def _handle_code_repair_request(payload: dict):
    """Create, but never dispatch, an auditable Codex repair task."""
    if not code_repair_ref:
        return
    try:
        request = str(payload.get("request") or "")
        proposal = code_repair_ref.propose(request)
        log_event(f"CODE_REPAIR_PROPOSED {proposal['action_id']}", stage="recovery")
    except (ValueError, RuntimeError) as exc:
        broadcast_msg("code_repair_result", {"status": "error", "message": str(exc)})


def _handle_code_repair_response(payload: dict):
    """Dispatch Codex only for the exact task the user approved."""
    if not code_repair_ref:
        return
    result = code_repair_ref.dispatch_if_approved(
        str(payload.get("action_id") or ""), payload.get("approved", False)
    )
    log_event(f"CODE_REPAIR_{result.get('status', 'unknown').upper()}", stage="recovery")
    broadcast_msg("code_repair_result", result)


def _restore_voice_mode() -> None:
    """Reload microphone ownership at startup.

    Without this, restarting the server would silently hand the microphone
    back to the classic path while Tommy still had Smooth Voice selected.
    """
    global VOICE_MODE
    VOICE_MODE = _load_voice_mode()
    logger.info("[VoiceMode] restored: %s owns the microphone", VOICE_MODE)


def _start_main_loop_thread():
    global main_loop_thread, SERVER_ENABLED
    if main_loop_thread and main_loop_thread.is_alive():
        return False
    SERVER_ENABLED = True
    main_loop_thread = threading.Thread(target=main_loop, daemon=True, name="ARGO.MainLoop")
    main_loop_thread.start()
    return True

class _QuietFailedHandshake(logging.Filter):
    """Drop the traceback for connections that never sent a request.

    A port check opens 8001 and closes it. websockets logs that as ERROR
    with a chained traceback, which buries real errors. The event is still
    recorded, as one line at debug level.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != "opening handshake failed":
            return True
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None and type(exc).__name__ == "InvalidMessage":
            record.exc_info = None
            record.msg = "ignored a connection that closed before sending a request"
            record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return True


async def start_server():
    global ui_loop
    ui_loop = asyncio.get_running_loop()
    logging.getLogger("websockets.server").addFilter(_QuietFailedHandshake())
    logger.info("UI Server running on ws://%s:%s/ws", WS_HOST, WS_PORT)
    while True:
        try:
            async with websockets.serve(websocket_handler, WS_HOST, WS_PORT) as server:
                logger.info("WebSocket server started, waiting for connections...")
                await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("WebSocket server cancelled")
            raise
        except Exception as e:
            logger.error(f"WebSocket server error: {e}", exc_info=True)
            await asyncio.sleep(1)

def main_loop():
    global LISTENING_ENABLED, SERVER_ENABLED, _noise_calibrate_fn
    # Wait briefly for UI server loop to be ready to capture early logs
    time.sleep(1)
    
    # Initialize Audio
    def on_owner_change(owner, contested):
        broadcast_msg("audio_owner", {"owner": owner, "contested": contested})

    audio = AudioManager(
        input_device_index=AUDIO_INPUT_INDEX,
        output_device_index=AUDIO_OUTPUT_INDEX,
        on_owner_change=on_owner_change,
    )
    pipeline = ArgoPipeline(audio, broadcast_msg)
    global pipeline_ref
    pipeline_ref = pipeline
    global audio_ref
    audio_ref = audio
    
    # Initialize assisted recovery system (Phase 1 & 2)
    _init_recovery_system()
    
    try:
        start_classic_runtime(audio, pipeline, config, broadcast_msg, logger)
    except Exception as e:
        logger.critical(f"Startup Failed: {e}")
        broadcast_msg("status", "ERROR")
        return
    
    def disable_listening() -> None:
        global LISTENING_ENABLED
        LISTENING_ENABLED = False

    def set_noise_calibrator(callback) -> None:
        global _noise_calibrate_fn
        _noise_calibrate_fn = callback

    run_classic_main_runtime(
        ClassicMainRuntime(
            audio=audio,
            pipeline=pipeline,
            config=config,
            environment=os.environ,
            get_server_enabled=lambda: SERVER_ENABLED,
            get_listening_enabled=lambda: LISTENING_ENABLED,
            disable_listening=disable_listening,
            get_voice_mode=lambda: VOICE_MODE,
            smooth_voice_mode=VOICE_MODE_SMOOTH,
            runtime_overrides=RUNTIME_OVERRIDES,
            input_sample_rate=INPUT_SAMPLE_RATE,
            block_size=BLOCK_SIZE,
            broadcast=broadcast_msg,
            logger=logger,
            calibrate_ambient_noise=calibrate_ambient_noise,
            set_noise_calibrator=set_noise_calibrator,
            run_capture_loop=run_classic_capture_loop,
            interrupt_current_response=_interrupt_current_response,
            next_interaction_overrides=NEXT_INTERACTION_OVERRIDES,
            sound_cues=sound_cues,
            event_logger=log_event,
        )
    )

if __name__ == "__main__":
    # Engine selection/loading belongs to STTEngineManager. The former local
    # Whisper preload was never used and also ran when cloud STT was selected.
    
    # Refuse to start wrong rather than start broken. The check reads
    # sys.PREFIX, not sys.executable: on Windows the venv python is a stub
    # that re-executes the base interpreter, so a perfectly healthy ARGO
    # reports a base-interpreter executable. Reading that as "wrong
    # interpreter" is how you end up killing the only working process.
    from core.runtime_guard import SingleInstance, verify_runtime

    verify_runtime("main")
    _instance_lock = SingleInstance("main").acquire()

    _restore_voice_mode()
    _start_main_loop_thread()
    
    from http.server import ThreadingHTTPServer
    FrontendHandler = _build_frontend_handler()
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), FrontendHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logger.info("Frontend HTTP server running on http://%s:%s", HTTP_HOST, HTTP_PORT)
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Shutdown requested via keyboard interrupt")
    except Exception as e:
        logger.error(f"Asyncio loop exited with error: {e}", exc_info=True)
    finally:
        try:
            _instance_lock.release()
        except Exception:
            pass
        logger.info("Main thread exiting")
