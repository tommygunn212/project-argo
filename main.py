
import asyncio
import websockets
import json
import threading
import logging
import numpy as np
import os
import sys
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

# Add core to path just in case
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.audio_manager import AudioManager
from core.pipeline import ArgoPipeline

# Thread-safe event loop reference BEFORE logging setup
ui_loop = None
connected_clients = set()
CURRENT_STATUS = "INITIALIZING"  # Stores the latest state to sync new clients

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
AUDIO_INPUT_INDEX = 36  # Speakerphone (Brio 500)
AUDIO_OUTPUT_INDEX = 4  # Speakers (M-Track)

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
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)

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
    # Wait briefly for UI server loop to be ready to capture early logs
    time.sleep(1)
    
    # Initialize Audio
    audio = AudioManager(input_device_index=AUDIO_INPUT_INDEX, output_device_index=AUDIO_OUTPUT_INDEX)
    pipeline = ArgoPipeline(audio, broadcast_msg)
    
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
    barge_in_threshold = 6.0
    
    logger.info("Starting in always-listening mode (VAD-based)")
    logger.info(f"VAD Threshold set to: {vad_threshold} (Lower = More Sensitive)")
    broadcast_msg("status", "LISTENING")
    
    speech_buffer = []
    is_recording = False
    silence_counter = 0
    silence_threshold = 30  # ~1.5 seconds
    
    while True:
        frame = audio.read_frame()
        if frame is None:
            continue
            
        # VAD Logic
        # Frame is float32. L2 Norm of 512 samples.
        volume = np.linalg.norm(frame) * 10
        
        # Trigger Recording
        if not pipeline.is_speaking and not is_recording and volume >= vad_threshold:
            logger.info(f"[VAD] Speech detected (volume: {volume:.2f}, threshold: {vad_threshold})")
            is_recording = True
            silence_counter = 0
            preroll = audio.get_preroll()
            if len(preroll) > 0:
                speech_buffer = [preroll]
            else:
                speech_buffer = []
            broadcast_msg("status", "RECORDING")
        
        # --- BARGE-IN: If speech detected during TTS ---
        if pipeline.is_speaking and volume >= barge_in_threshold:
            logger.info("!!! BARGE-IN TRIGGERED: Interrupting TTS !!!")
            pipeline.stop_signal.set()
            audio.stop_playback() # Kill audio immediately
            
            # Reset state to listen to new command
            silence_counter = 0
            if not is_recording:
                is_recording = True
                preroll = audio.get_preroll()
                speech_buffer = [preroll] if len(preroll) > 0 else []
        
        if is_recording:
            speech_buffer.append(frame)
            
            if volume < vad_threshold:
                silence_counter += 1
            else:
                silence_counter = 0
                
            # Stop Recording after silence
            if silence_counter > silence_threshold:
                is_recording = False
                silence_counter = 0
                
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
                        t = threading.Thread(target=pipeline.run_interaction, args=(full_audio,))
                        t.start()
                    else:
                        logger.warning(f"[Audio] Input too quiet/silent (peak: {peak:.4f}), ignoring")
                        audio.clear_buffers()
                else:
                    audio.clear_buffers()

if __name__ == "__main__":
    t = threading.Thread(target=main_loop, daemon=True)
    t.start()
    
    from http.server import HTTPServer
    server = HTTPServer(('localhost', 8000), FrontendHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logger.info("Frontend HTTP server running on http://localhost:8000")
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        pass
