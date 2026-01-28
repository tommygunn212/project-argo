
import asyncio
import websockets
import json
import threading
import logging
import numpy as np
import os
import sys
import time
import uuid
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

# Add core to path just in case
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(repo_root)

# Ensure Piper binary is on PATH (clean startup)
local_piper_dir = os.path.join(repo_root, "audio", "piper")
system_piper_dir = "C:\\piper"
path_prefixes = []
if os.path.isdir(local_piper_dir):
    path_prefixes.append(local_piper_dir)
if os.path.isdir(system_piper_dir):
    path_prefixes.append(system_piper_dir)
if path_prefixes:
    os.environ["PATH"] = os.pathsep.join(path_prefixes) + os.pathsep + os.environ.get("PATH", "")

from core.audio_manager import AudioManager
from core.pipeline import ArgoPipeline
from core.instrumentation import log_event
from core.config import (
    get_config,
    get_config_hash,
    get_runtime_overrides,
    set_runtime_override,
    set_runtime_overrides,
    clear_runtime_overrides,
)

# Thread-safe event loop reference BEFORE logging setup
ui_loop = None
connected_clients = set()
CURRENT_STATUS = "INITIALIZING"  # Stores the latest state to sync new clients
pipeline_ref = None
audio_ref = None
LISTENING_ENABLED = False
SERVER_ENABLED = True
main_loop_thread = None

# Custom logging handler to broadcast logs via WebSocket
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

# Hardware Config
config = get_config()
AUDIO_INPUT_INDEX = config.get("audio.input_device_index")
AUDIO_OUTPUT_INDEX = config.get("audio.output_device_index")

# Runtime control
RUNTIME_OVERRIDES = get_runtime_overrides()
NEXT_INTERACTION_OVERRIDES = {}

def broadcast_msg(msg_type, data):
    """Bridge between Sync Backend and Async UI."""
    global CURRENT_STATUS
    
    # Update state memory
    if msg_type == "status":
        CURRENT_STATUS = data
        
    if ui_loop and ui_loop.is_running():
        msg = json.dumps({"type": msg_type, "payload": data})
        asyncio.run_coroutine_threadsafe(send_to_clients(msg), ui_loop)

class FrontendHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            status_json = json.dumps({
                "status": "ok",
                "service": "ARGO Local Voice Assistant",
                "ws_endpoint": "ws://localhost:8001/ws"
            })
            self.wfile.write(status_json.encode())
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            try:
                content = (Path(__file__).parent / 'frontend' / 'index.html').read_bytes()
            except FileNotFoundError:
                content = (Path(__file__).parent / 'index.html').read_bytes()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

async def send_to_clients(msg):
    if not connected_clients:
        return
    for ws in list(connected_clients):
        try:
            await ws.send(msg)
        except:
            connected_clients.discard(ws)

async def websocket_handler(websocket):
    connected_clients.add(websocket)
    try:
        # Immediately sync status on connection so UI doesn't stay "Initializing"
        await websocket.send(json.dumps({"type": "status", "payload": CURRENT_STATUS}))
        await websocket.send(json.dumps({"type": "config", "payload": {"hash": get_config_hash()}}))
        await websocket.send(json.dumps({"type": "runtime_overrides", "payload": get_runtime_overrides()}))
        await websocket.send(json.dumps({"type": "audio_owner", "payload": {"owner": "UNKNOWN", "contested": False}}))

        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue
            msg_type = data.get("type")
            payload = data.get("payload")
            if msg_type == "set_voice" and pipeline_ref:
                pipeline_ref.set_voice(payload)
            if msg_type == "replay" and pipeline_ref and payload:
                t = threading.Thread(target=pipeline_ref.replay_interaction, args=(payload,), daemon=True)
                t.start()
            if msg_type == "control" and payload:
                _handle_control(payload)
            if msg_type == "override" and payload:
                _handle_override(payload)
            if msg_type == "next_override" and payload:
                _handle_next_override(payload)
            if msg_type == "clear_overrides":
                _handle_clear_overrides()
    finally:
        connected_clients.discard(websocket)


def _handle_control(command):
    global LISTENING_ENABLED, SERVER_ENABLED
    cmd = None
    data = {}
    if isinstance(command, dict):
        cmd = str(command.get("command", "")).upper()
        data = command.get("data", {}) or {}
    else:
        cmd = str(command).upper()
    if cmd == "PAUSE":
        log_event("UI_CMD_STOP_VAD", stage="ui")
        LISTENING_ENABLED = False
        log_event("CONTROL_PAUSE", stage="control")
        if pipeline_ref:
            pipeline_ref.transition_state("IDLE", source="ui")
        if audio_ref:
            try:
                audio_ref.stop()
            except Exception:
                pass
        broadcast_msg("status", "IDLE")
    elif cmd == "RESUME":
        log_event("UI_CMD_START_VAD", stage="ui")
        LISTENING_ENABLED = True
        log_event("CONTROL_RESUME", stage="control")
        if audio_ref:
            try:
                audio_ref.start()
            except Exception:
                pass
        if pipeline_ref:
            pipeline_ref.transition_state("LISTENING", source="ui")
    elif cmd == "SERVER_STOP":
        log_event("UI_CMD_STOP_SERVER", stage="ui")
        log_event("CONTROL_SERVER_STOP", stage="control")
        broadcast_msg("log", "Server stopping (pipeline thread)...")
        SERVER_ENABLED = False
        LISTENING_ENABLED = False
        if audio_ref:
            try:
                audio_ref.stop()
            except Exception:
                pass
        broadcast_msg("status", "IDLE")
    elif cmd == "SERVER_START":
        log_event("UI_CMD_START_SERVER", stage="ui")
        log_event("CONTROL_SERVER_START", stage="control")
        started = _start_main_loop_thread()
        broadcast_msg("log", "Server start requested" if started else "Server already running")
    elif cmd == "SERVER_RESTART":
        log_event("UI_CMD_RESTART_SERVER", stage="ui")
        log_event("CONTROL_SERVER_RESTART", stage="control")
        SERVER_ENABLED = False
        LISTENING_ENABLED = False
        if audio_ref:
            try:
                audio_ref.stop()
            except Exception:
                pass
        time.sleep(0.3)
        started = _start_main_loop_thread()
        broadcast_msg("log", "Server restart requested" if started else "Server already running")
    elif cmd == "FORCE_RELEASE_AUDIO":
        log_event("UI_CMD_FORCE_RELEASE_AUDIO", stage="ui")
        if audio_ref:
            try:
                audio_ref.force_release_audio("UI_FORCE_RELEASE")
                audio_ref.stop_playback()
            except Exception:
                pass
        if pipeline_ref:
            try:
                pipeline_ref.stop_signal.set()
            except Exception:
                pass
    elif cmd == "RESET_INTERACTION":
        log_event("UI_CMD_RESET_INTERACTION", stage="ui")
        if pipeline_ref:
            try:
                pipeline_ref.reset_interaction()
            except Exception:
                pass
        broadcast_msg("status", "LISTENING")
    elif cmd == "FULL_RESET" or cmd == "FORCE_RESET":
        log_event("UI_CMD_FORCE_RESET", stage="ui")
        SERVER_ENABLED = False
        LISTENING_ENABLED = False
        if audio_ref:
            try:
                audio_ref.stop()
            except Exception:
                pass
        if pipeline_ref:
            try:
                pipeline_ref.stop_signal.set()
            except Exception:
                pass
        _handle_clear_overrides()
        NEXT_INTERACTION_OVERRIDES.clear()
        time.sleep(0.3)
        started = _start_main_loop_thread()
        broadcast_msg("log", "Full reset requested" if started else "Server already running")


def _handle_override(payload: dict):
    key = payload.get("key")
    value = payload.get("value")
    if not key:
        return
    set_runtime_override(key, value)
    if key == "debug_level":
        try:
            logging.getLogger().setLevel(str(value).upper())
        except Exception:
            pass
    log_event(f"UI_CMD_SET_OVERRIDE {key}={value}", stage="ui")
    broadcast_msg("runtime_overrides", get_runtime_overrides())


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


def _start_main_loop_thread():
    global main_loop_thread, SERVER_ENABLED
    if main_loop_thread and main_loop_thread.is_alive():
        return False
    SERVER_ENABLED = True
    main_loop_thread = threading.Thread(target=main_loop, daemon=True, name="ARGO.MainLoop")
    main_loop_thread.start()
    return True

async def start_server():
    global ui_loop
    ui_loop = asyncio.get_running_loop()
    logger.info("UI Server running on ws://localhost:8001/ws")
    while True:
        try:
            async with websockets.serve(websocket_handler, "localhost", 8001) as server:
                await asyncio.Future()
        except Exception as e:
            logger.error(f"WebSocket server error: {e}", exc_info=True)
            await asyncio.sleep(1)

def main_loop():
    global LISTENING_ENABLED, SERVER_ENABLED
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
    
    try:
        audio.start()
        pipeline.warmup()
    except Exception as e:
        logger.critical(f"Startup Failed: {e}")
        broadcast_msg("status", "ERROR")
        return
    
    # --- VAD SETTINGS ---
    # Lower threshold = Easier to interrupt / easier to trigger
    vad_threshold = 3.0
    barge_in_threshold = 4.0
    
    if LISTENING_ENABLED:
        logger.info("Starting in always-listening mode (VAD-based)")
        logger.info(f"VAD Threshold set to: {vad_threshold} (Lower = More Sensitive)")
        pipeline.transition_state("LISTENING")
    else:
        logger.info("Starting with VAD paused")
        logger.info(f"VAD Threshold set to: {vad_threshold} (Lower = More Sensitive)")
        pipeline.transition_state("IDLE")
        broadcast_msg("status", "IDLE")
    
    speech_buffer = []
    is_recording = False
    silence_counter = 0
    silence_threshold = 30  # ~1.5 seconds
    current_interaction_id = ""
    
    while SERVER_ENABLED:
        if pipeline.illegal_transition:
            LISTENING_ENABLED = False
            time.sleep(0.1)
            continue
        if not LISTENING_ENABLED:
            time.sleep(0.1)
            continue
        frame = audio.read_frame()
        if frame is None:
            continue
            
        # VAD Logic
        # Frame is float32. L2 Norm of 512 samples.
        volume = np.linalg.norm(frame) * 10
        
        owner = audio.get_audio_owner() if audio else "NONE"
        passive_listen = owner not in ("NONE", "STT")

        # Trigger Recording (only when LISTENING to avoid illegal transitions)
        if (
            not passive_listen
            and not pipeline.is_speaking
            and not is_recording
            and volume >= vad_threshold
            and pipeline.current_state == "LISTENING"
        ):
            current_interaction_id = str(uuid.uuid4())
            logger.info(f"[VAD] Speech detected (volume: {volume:.2f}, threshold: {vad_threshold})")
            log_event(
                f"VAD_START rms={volume:.2f} threshold={vad_threshold}",
                stage="vad",
                interaction_id=current_interaction_id,
            )
            is_recording = True
            silence_counter = 0
            preroll = audio.get_preroll()
            if len(preroll) > 0:
                speech_buffer = [preroll]
            else:
                speech_buffer = []
            pipeline.transition_state("TRANSCRIBING", interaction_id=current_interaction_id)
        
        # --- BARGE-IN: If speech detected during TTS ---
        if pipeline.is_speaking and volume >= barge_in_threshold and RUNTIME_OVERRIDES.get("barge_in_enabled", True):
            allowed = pipeline.current_state == "SPEAKING"
            logger.info("!!! BARGE-IN TRIGGERED: Interrupting TTS !!!")
            log_event(
                f"BARGE_IN rms={volume:.2f} threshold={barge_in_threshold} stage={pipeline.current_state} allowed={allowed}",
                stage="audio",
                interaction_id=pipeline.current_interaction_id,
            )
            broadcast_msg("barge_in", {
                "interaction_id": pipeline.current_interaction_id,
                "rms": float(volume),
                "threshold": float(barge_in_threshold),
                "stage": str(pipeline.current_state),
                "allowed": bool(allowed),
            })
            pipeline.stop_signal.set()
            audio.force_release_audio("BARGE_IN", interaction_id=pipeline.current_interaction_id)
            audio.stop_playback() # Kill audio immediately
            pipeline.is_speaking = False
            try:
                pipeline.force_state("LISTENING", interaction_id=pipeline.current_interaction_id, source="BARGE_IN")
            except Exception:
                pass
            
            # Reset state to listen to new command
            silence_counter = 0
            if not is_recording:
                is_recording = True
                preroll = audio.get_preroll()
                speech_buffer = [preroll] if len(preroll) > 0 else []
        
        if is_recording and not passive_listen:
            speech_buffer.append(frame)
            
            if volume < vad_threshold:
                silence_counter += 1
            else:
                silence_counter = 0
                
            # Stop Recording after silence
            if silence_counter > silence_threshold:
                is_recording = False
                silence_counter = 0
                log_event("VAD_END", stage="vad", interaction_id=current_interaction_id)
                
                # Process Audio
                if len(speech_buffer) > 0:
                    full_audio = np.concatenate(speech_buffer)
                    
                    # --- AUDIO NORMALIZATION ---
                    peak = np.max(np.abs(full_audio))
                    if peak > 0.01: 
                        normalization_factor = 0.9 / peak
                        full_audio = full_audio * normalization_factor
                        logger.info(f"[Audio] Normalized input (original peak: {peak:.4f} -> 0.9)")

                        # CRITICAL FIX: Squeeze 2D array (N, 1) -> 1D array (N,)
                        full_audio = np.squeeze(full_audio)
                        
                        audio.clear_buffers()
                        
                        # Offload to pipeline
                        overrides = dict(NEXT_INTERACTION_OVERRIDES)
                        NEXT_INTERACTION_OVERRIDES.clear()
                        t = threading.Thread(
                            target=pipeline.run_interaction,
                            args=(full_audio, current_interaction_id, False, overrides),
                        )
                        t.start()
                        current_interaction_id = ""
                    else:
                        logger.warning(f"[Audio] Input too quiet/silent (peak: {peak:.4f}), ignoring")
                        audio.clear_buffers()
                else:
                    audio.clear_buffers()

if __name__ == "__main__":
    _start_main_loop_thread()
    
    from http.server import HTTPServer
    server = HTTPServer(('localhost', 8000), FrontendHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logger.info("Frontend HTTP server running on http://localhost:8000")
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        pass
