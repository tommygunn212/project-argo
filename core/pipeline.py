
"""
ARGO Pipeline: STT -> LLM -> TTS

Synchronous, queue-based processing pipeline.
Uses faster-whisper, ollama, and piper.
"""

import time
import logging
import numpy as np
import threading
import sys
from faster_whisper import WhisperModel
import ollama
import subprocess
import shutil
import os
from pathlib import Path

class ArgoPipeline:
    def __init__(self, audio_manager, websocket_broadcast):
        self.logger = logging.getLogger("ARGO.Pipeline")
        self.audio = audio_manager
        self.broadcast = websocket_broadcast
        self.stop_signal = threading.Event()
        self.is_speaking = False
        
        # Concurrency Lock
        self.processing_lock = threading.Lock()
        
        # Models
        self.stt_model = None
        self.tts_process = None
        
        # Default voice
        self.voices = {
            "lessac": "audio/piper/voices/en_US-lessac-medium.onnx",
            "alan": "audio/piper/voices/en_GB-alan-low.onnx"
        }
        self.current_voice_key = "lessac"
        self.piper_model_path = self.voices["lessac"]
        
        if not shutil.which("piper"):
            self.logger.warning("Piper not in PATH (but module callable via 'python -m piper')")

    def set_voice(self, voice_key):
        """Switch the TTS voice model."""
        if voice_key in self.voices:
            new_path = self.voices[voice_key]
            if os.path.exists(new_path):
                self.current_voice_key = voice_key
                self.piper_model_path = new_path
                self.logger.info(f"Voice switched to {voice_key}: {new_path}")
                self.broadcast("log", f"System: Voice profile switched to {voice_key.upper()}")
                return True
            else:
                self.logger.error(f"Voice file missing: {new_path}")
                self.broadcast("log", f"ERROR: Voice file for {voice_key.upper()} not found at {new_path}")
                return False
        return False

    def warmup(self):
        self.logger.info("Warming up models...")
        self.broadcast("status", "WARMING_UP")
        
        try:
            cache_dir = Path(__file__).resolve().parent.parent / ".hf_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HOME", str(cache_dir))
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_dir / "hub"))

            self.logger.info("Loading Whisper Model: base.en...")
            try:
                self.stt_model = WhisperModel("base.en", device="cuda", compute_type="float16")
            except Exception as cuda_error:
                self.logger.warning(f"STT CUDA init failed, falling back to CPU: {cuda_error}")
                self.stt_model = WhisperModel("base.en", device="cpu", compute_type="int8")
            # Run a dummy transcription to load into VRAM
            self.stt_model.transcribe(np.zeros(16000, dtype='float32'), beam_size=1)
            self.logger.info("STT model warmed up")
        except Exception as e:
            self.logger.error(f"STT Warmup Error: {e}")
        
        try:
            client = ollama.Client(host='http://127.0.0.1:11434')
            client.generate(model='qwen2:latest', prompt='hi', stream=False)
            self.logger.info("LLM model warmed up")
        except Exception as e:
            self.logger.warning(f"LLM Warmup Warning: {e}")
        
        self.broadcast("status", "READY")

    def transcribe(self, audio_data):
        if self.stt_model is None:
            self.logger.error("[STT] Model not initialized")
            return ""
        self.logger.info(f"[STT] Starting transcription... Audio len: {len(audio_data)}")
        start = time.perf_counter()
        try:
            segments, info = self.stt_model.transcribe(
                audio_data, 
                beam_size=5, 
                language="en",
                condition_on_previous_text=False
            )
            segments_list = list(segments)
            text = " ".join([s.text for s in segments_list]).strip()
            
            for i, seg in enumerate(segments_list):
                confidence = np.exp(seg.avg_logprob)
                self.logger.info(f"  Seg {i}: '{seg.text}' ({confidence:.2f})")
            
            duration = (time.perf_counter() - start) * 1000
            self.logger.info(f"[STT] Done in {duration:.0f}ms: '{text}'")
            return text
        except Exception as e:
            self.logger.error(f"[STT] Failed: {e}", exc_info=True)
            return ""

    def generate_response(self, text):
        self.logger.info(f"[LLM] Prompt: '{text}'")
        full_response = ""
        try:
            client = ollama.Client(host='http://127.0.0.1:11434')
            stream = client.generate(model='qwen2:latest', prompt=text, stream=True)
            
            for chunk in stream:
                if self.stop_signal.is_set():
                    break
                part = chunk.get('response', '')
                full_response += part
                
            self.logger.info(f"[LLM] Response: '{full_response[:60]}...'")
            return full_response
        except Exception as e:
            self.logger.error(f"[LLM] Error: {e}")
            return "[Error connecting to LLM]"

    def speak(self, text):
        self.logger.info(f"[TTS] Speaking with {self.current_voice_key}...")
        self.broadcast("status", "SPEAKING")
        self.stop_signal.clear()
        self.is_speaking = True
        
        cmd = [sys.executable, "-m", "piper", "--model", self.piper_model_path, "--output-raw"]
        
        try:
            self.tts_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            if self.tts_process.stdin:
                self.tts_process.stdin.write(text.encode('utf-8'))
                self.tts_process.stdin.close()

            while True:
                if self.stop_signal.is_set():
                    self.tts_process.terminate()
                    break
                data = self.tts_process.stdout.read(4096)
                if not data: break
                self.audio.play_chunk(np.frombuffer(data, dtype='int16'))
            
            self.tts_process.wait()
        except Exception as e:
            self.logger.error(f"[TTS] Error: {e}")
        finally:
            self.is_speaking = False

    def run_interaction(self, audio_data):
        # THREAD SAFETY: Prevent overlapping runs which can crash models
        if not self.processing_lock.acquire(blocking=False):
            self.logger.warning("[PIPELINE] Ignored input - System busy processing previous request")
            return

        try:
            # Reset any prior barge-in state
            self.stop_signal.clear()
            self.logger.info(f"--- Starting Interaction ({len(audio_data)} samples) ---")
            self.broadcast("status", "PROCESSING")
            
            # Print to stdout just in case logger fails
            print(f"DEBUG: Processing audio... {audio_data.shape}")
            
            user_text = self.transcribe(audio_data)
            if not user_text:
                self.logger.warning("No speech recognized.")
                self.broadcast("status", "WAITING")
                return

            self.broadcast("log", f"User: {user_text}")
            
            ai_text = self.generate_response(user_text)
            if not ai_text.strip():
                self.logger.warning("[LLM] Empty response")
                self.broadcast("log", "Argo: [No response]")
                return
            self.broadcast("log", f"Argo: {ai_text}")

            if not self.stop_signal.is_set():
                self.speak(ai_text)
            
            self.broadcast("status", "WAITING")
            self.logger.info("--- Interaction Complete ---")
            
        except Exception as e:
            self.logger.error(f"Pipeline Error: {e}", exc_info=True)
            self.broadcast("status", "ERROR")
        finally:
            self.processing_lock.release()
