
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
import uuid
import json
import re
from faster_whisper import WhisperModel
import ollama
import subprocess
import shutil
import os
from pathlib import Path

from core.instrumentation import log_event
from core.config import get_runtime_overrides

class ArgoPipeline:
    def __init__(self, audio_manager, websocket_broadcast):
        self.logger = logging.getLogger("ARGO.Pipeline")
        self.audio = audio_manager
        self.broadcast = websocket_broadcast
        self.stop_signal = threading.Event()
        self.is_speaking = False
        self.current_interaction_id = ""
        self.illegal_transition_details = None
        self.timeline_events = []
        self.runtime_overrides = get_runtime_overrides()

        # State machine
        self._state_lock = threading.Lock()
        self.current_state = "IDLE"
        self.illegal_transition = False
        self.ALLOWED_TRANSITIONS = {
            "IDLE": {"LISTENING"},
            "LISTENING": {"TRANSCRIBING"},
            "TRANSCRIBING": {"THINKING", "LISTENING", "IDLE"},
            "THINKING": {"SPEAKING", "IDLE"},
            "SPEAKING": {"LISTENING", "IDLE"},
        }
        
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

    def _sanitize_tts_text(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        cleaned = text
        # Strip markdown emphasis and inline code markers
        cleaned = re.sub(r"[`*_#]+", "", cleaned)
        # Convert markdown links: [text](url) -> text
        cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
        # Remove list bullets
        cleaned = re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

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

    def _record_timeline(self, event: str, stage: str, interaction_id: str = ""):
        ts = int(time.monotonic() * 1000)
        self.timeline_events.append({
            "t": ts,
            "id": interaction_id,
            "stage": stage,
            "event": event,
        })
        log_event(event, stage=stage, interaction_id=interaction_id)

    def transition_state(self, new_state: str, interaction_id: str = "", source: str = "audio") -> bool:
        with self._state_lock:
            old_state = self.current_state
            if new_state == old_state:
                return True
            allowed = new_state in self.ALLOWED_TRANSITIONS.get(old_state, set())
            if not allowed:
                self.illegal_transition = True
                payload = {
                    "from": old_state,
                    "to": new_state,
                    "allowed": list(self.ALLOWED_TRANSITIONS.get(old_state, set())),
                    "source": source,
                    "interaction_id": interaction_id,
                }
                self.illegal_transition_details = payload
                self._record_timeline(
                    f"ILLEGAL_TRANSITION {old_state}->{new_state} source={source}",
                    stage="state",
                    interaction_id=interaction_id,
                )
                self.broadcast("illegal_transition", payload)
                self.broadcast("status", "ERROR")
                self.broadcast("log", f"ILLEGAL TRANSITION: {old_state} → {new_state}")
                if self.is_speaking:
                    try:
                        self.stop_signal.set()
                        self.audio.force_release_audio("ILLEGAL_TRANSITION", interaction_id=interaction_id)
                        self.audio.stop_playback()
                    except Exception:
                        pass
                return False
            self.current_state = new_state
            self._record_timeline(
                f"STATE {old_state}->{new_state}",
                stage="state",
                interaction_id=interaction_id,
            )
            self.broadcast("status", new_state)
            return True

    def force_state(self, new_state: str, interaction_id: str = "", source: str = "BARGE_IN"):
        with self._state_lock:
            old_state = self.current_state
            self.current_state = new_state
            self._record_timeline(
                f"STATE {old_state}->{new_state} (forced, source={source})",
                stage="state",
                interaction_id=interaction_id,
            )
            self.broadcast("status", new_state)

    def reset_interaction(self):
        self.stop_signal.set()
        self.is_speaking = False
        self.illegal_transition = False
        self.illegal_transition_details = None
        self.transition_state("LISTENING", source="ui")

    def transcribe(self, audio_data, interaction_id: str = ""):
        if self.stt_model is None:
            self.logger.error("[STT] Model not initialized")
            return ""
        self.logger.info(f"[STT] Starting transcription... Audio len: {len(audio_data)}")
        self._record_timeline("STT_START", stage="stt", interaction_id=interaction_id)
        start = time.perf_counter()
        try:
            # Basic audio metrics
            duration_s = len(audio_data) / 16000.0 if len(audio_data) else 0
            rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) else 0.0
            peak = float(np.max(np.abs(audio_data))) if len(audio_data) else 0.0
            silence_ratio = float(np.mean(np.abs(audio_data) < 0.01)) if len(audio_data) else 1.0

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
            confidence_proxy = 0.0
            if duration_s > 0:
                confidence_proxy = min(1.0, (len(text) / max(1.0, duration_s * 10)) * (1.0 - silence_ratio))
            self._record_timeline(
                f"STT_DONE len={len(text)} rms={rms:.4f} peak={peak:.4f} silence={silence_ratio:.2f} conf={confidence_proxy:.2f}",
                stage="stt",
                interaction_id=interaction_id,
            )
            self.broadcast("stt_metrics", {
                "interaction_id": interaction_id,
                "text_len": len(text),
                "duration_s": duration_s,
                "rms": rms,
                "peak": peak,
                "silence_ratio": silence_ratio,
                "confidence": confidence_proxy,
            })
            return text
        except Exception as e:
            self.logger.error(f"[STT] Failed: {e}", exc_info=True)
            self._record_timeline("STT_ERROR", stage="stt", interaction_id=interaction_id)
            return ""

    def generate_response(self, text, interaction_id: str = ""):
        self.logger.info(f"[LLM] Prompt: '{text}'")
        full_response = ""
        try:
            client = ollama.Client(host='http://127.0.0.1:11434')
            self._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
            start = time.perf_counter()
            first_token_ms = None
            stream = client.generate(model='qwen2:latest', prompt=text, stream=True)
            
            for chunk in stream:
                if self.stop_signal.is_set():
                    break
                part = chunk.get('response', '')
                if part and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    self._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm",
                        interaction_id=interaction_id,
                    )
                full_response += part
            total_ms = (time.perf_counter() - start) * 1000
            self._record_timeline(
                f"LLM_DONE {total_ms:.0f}ms",
                stage="llm",
                interaction_id=interaction_id,
            )
            self.broadcast("llm_metrics", {
                "interaction_id": interaction_id,
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
            })
            self.logger.info(f"[LLM] Response: '{full_response[:60]}...'")
            return full_response
        except Exception as e:
            self.logger.error(f"[LLM] Error: {e}")
            self._record_timeline("LLM_ERROR", stage="llm", interaction_id=interaction_id)
            return "[Error connecting to LLM]"

    def speak(self, text, interaction_id: str = ""):
        if not self.runtime_overrides.get("tts_enabled", True):
            self.logger.info("[TTS] Disabled by runtime override")
            return
        self.logger.info(f"[TTS] Speaking with {self.current_voice_key}...")
        self.transition_state("SPEAKING", interaction_id=interaction_id, source="tts")
        self.stop_signal.clear()
        self.is_speaking = True
        self._record_timeline("TTS_START", stage="tts", interaction_id=interaction_id)
        
        piper_exe = shutil.which("piper")
        if piper_exe:
            cmd = [piper_exe, "--model", self.piper_model_path, "--output-raw"]
        else:
            cmd = [sys.executable, "-m", "piper", "--model", self.piper_model_path, "--output-raw"]
        
        try:
            try:
                self.audio.acquire_audio("TTS", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[TTS] Audio ownership error: {e}")
                log_event("TTS_AUDIO_CONTESTED", stage="audio", interaction_id=interaction_id)
                return
            self.tts_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                if self.tts_process.stdout:
                    os.set_blocking(self.tts_process.stdout.fileno(), False)
            except Exception:
                pass
            if self.tts_process.stdin:
                try:
                    self.tts_process.stdin.write(text.encode('utf-8'))
                except BrokenPipeError:
                    self.logger.warning("[TTS] Piper stdin broken pipe during write")
                finally:
                    try:
                        self.tts_process.stdin.close()
                    except Exception:
                        pass

            while True:
                if self.stop_signal.is_set():
                    try:
                        self.tts_process.terminate()
                        self.tts_process.wait(timeout=0.2)
                    except Exception:
                        try:
                            self.tts_process.kill()
                        except Exception:
                            pass
                    break
                data = b""
                try:
                    if self.tts_process.stdout:
                        data = self.tts_process.stdout.read(4096)
                except BlockingIOError:
                    data = b""
                if data:
                    self.audio.play_chunk(np.frombuffer(data, dtype='int16'))
                else:
                    if self.tts_process.poll() is not None:
                        break
                    time.sleep(0.01)
            
            try:
                self.tts_process.wait()
            except Exception:
                pass
        except Exception as e:
            self.logger.error(f"[TTS] Error: {e}")
        finally:
            try:
                if self.tts_process and self.tts_process.stdout:
                    self.tts_process.stdout.close()
            except Exception:
                pass
            self.audio.release_audio("TTS", interaction_id=interaction_id)
            self.is_speaking = False
            self._record_timeline("TTS_DONE", stage="tts", interaction_id=interaction_id)

    def run_interaction(self, audio_data, interaction_id: str = "", replay_mode: bool = False, overrides: dict | None = None):
        # THREAD SAFETY: Prevent overlapping runs which can crash models
        if not self.processing_lock.acquire(blocking=False):
            self.logger.warning("[PIPELINE] Ignored input - System busy processing previous request")
            return

        try:
            # Reset any prior barge-in state
            self.stop_signal.clear()
            self.timeline_events = []
            if not interaction_id:
                interaction_id = str(uuid.uuid4())
            self.current_interaction_id = interaction_id
            self.logger.info(f"--- Starting Interaction ({len(audio_data)} samples) ---")
            self._record_timeline("INTERACTION_START", stage="pipeline", interaction_id=interaction_id)
            self.transition_state("TRANSCRIBING", interaction_id=interaction_id, source="audio")
            
            # Print to stdout just in case logger fails
            print(f"DEBUG: Processing audio... {audio_data.shape}")

            try:
                self.audio.acquire_audio("STT", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[STT] Audio ownership error: {e}")
                self._record_timeline("STT_AUDIO_CONTESTED", stage="audio", interaction_id=interaction_id)
                return

            user_text = self.transcribe(audio_data, interaction_id=interaction_id)
            self.audio.release_audio("STT", interaction_id=interaction_id)
            if not user_text:
                self.logger.warning("No speech recognized.")
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return

            self.broadcast("log", f"User: {user_text}")

            self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
            ai_text = self.generate_response(user_text, interaction_id=interaction_id)
            if not ai_text.strip():
                self.logger.warning("[LLM] Empty response")
                self.broadcast("log", "Argo: [No response]")
                return
            self.broadcast("log", f"Argo: {ai_text}")

            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(ai_text)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
                else:
                    self.logger.warning("[TTS] Sanitized response is empty, skipping TTS")
            
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self.logger.info("--- Interaction Complete ---")
            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)

            if not replay_mode:
                self._save_replay(
                    interaction_id=interaction_id,
                    audio_data=audio_data,
                    user_text=user_text,
                    ai_text=ai_text,
                )
            
        except Exception as e:
            self.logger.error(f"Pipeline Error: {e}", exc_info=True)
            self.broadcast("status", "ERROR")
            self._record_timeline("PIPELINE_ERROR", stage="pipeline", interaction_id=interaction_id)
        finally:
            self.processing_lock.release()

    def _save_replay(self, interaction_id: str, audio_data, user_text: str, ai_text: str):
        try:
            replay_dir = Path("runtime") / "replays"
            replay_dir.mkdir(parents=True, exist_ok=True)
            audio_path = replay_dir / f"{interaction_id}.npy"
            np.save(audio_path, audio_data)
            payload = {
                "interaction_id": interaction_id,
                "created_at": time.time(),
                "audio_path": str(audio_path),
                "stt_text": user_text,
                "intent": "direct",
                "llm_prompt": user_text,
                "llm_response": ai_text,
                "timeline_events": list(self.timeline_events),
            }
            json_path = replay_dir / f"{interaction_id}.json"
            json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.broadcast("replay_saved", {
                "interaction_id": interaction_id,
                "created_at": payload["created_at"],
            })
        except Exception as e:
            self.logger.warning(f"Replay save failed: {e}")

    def replay_interaction(self, interaction_id: str):
        replay_dir = Path("runtime") / "replays"
        json_path = replay_dir / f"{interaction_id}.json"
        audio_path = replay_dir / f"{interaction_id}.npy"
        if not json_path.exists() or not audio_path.exists():
            self.logger.warning(f"Replay not found for {interaction_id}")
            return
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            log_event("REPLAY_START", stage="replay", interaction_id=interaction_id)
            self.broadcast("status", "TRANSCRIBING")
            self.broadcast("log", f"User: {payload.get('stt_text', '')}")
            self.broadcast("status", "THINKING")
            self.broadcast("log", f"Argo: {payload.get('llm_response', '')}")
            self.broadcast("status", "LISTENING")
            log_event("REPLAY_END", stage="replay", interaction_id=interaction_id)
        except Exception as e:
            self.logger.error(f"Replay error: {e}")
