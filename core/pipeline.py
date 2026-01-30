
"""
ARGO Pipeline: STT -> LLM -> TTS

Synchronous, queue-based processing pipeline.
Uses faster-whisper, ollama, and piper.
"""

# ============================================================================
# 1) IMPORTS
# ============================================================================
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
from core.config import get_runtime_overrides, get_config
from core.intent_parser import RuleBasedIntentParser, IntentType, normalize_system_text, is_system_keyword
from core.music_player import get_music_player
from core.music_status import query_music_status
from system_health import (
    get_system_health,
    get_memory_info,
    get_temperatures,
    get_temperature_health,
    get_disk_info,
    get_system_full_report,
)
from system_profile import get_system_profile, get_gpu_profile

# ============================================================================
# 2) PIPELINE ORCHESTRATOR
# ============================================================================
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
        try:
            self._config = get_config()
        except Exception:
            self._config = None
        self._intent_parser = RuleBasedIntentParser()
        self._last_stt_metrics = None
        self._low_conf_notice_given = False
        self._serious_mode_keywords = {
            "help", "urgent", "emergency", "panic", "stuck", "broken", "crash",
            "error", "fail", "failure", "frustrated", "angry", "upset",
            "deadline", "production", "incident", "outage",
        }
        self.llm_enabled = True

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
            "alan": "audio/piper/voices/en_GB-alan-medium.onnx",
            "alba": "audio/piper/voices/en_GB-alba-medium.onnx"
        }
        self.current_voice_key = "lessac"
        self.piper_model_path = self.voices["lessac"]
        
        if not shutil.which("piper"):
            self.logger.warning("Piper not in PATH (but module callable via 'python -m piper')")

    def set_voice(self, voice_key):
        """Switch the TTS voice model."""
        if voice_key in self.voices:
            new_path = self.voices[voice_key]
            config_path = f"{new_path}.json"
            if os.path.exists(new_path) and os.path.exists(config_path):
                self.current_voice_key = voice_key
                self.piper_model_path = new_path
                self.logger.info(f"Voice switched to {voice_key}: {new_path}")
                self.broadcast("log", f"System: Voice profile switched to {voice_key.upper()}")
                return True
            else:
                missing = []
                if not os.path.exists(new_path):
                    missing.append(new_path)
                if not os.path.exists(config_path):
                    missing.append(config_path)
                missing_str = ", ".join(missing)
                self.logger.error(f"Voice files missing: {missing_str}")
                self.broadcast("log", f"ERROR: Voice files missing for {voice_key.upper()}: {missing_str}")
                return False
        return False

    def _sanitize_tts_text(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        cleaned = text
        # Remove system diagnostics from spoken output
        cleaned = re.sub(r"\b(VAD|STT|LLM|TTS|AUDIO|THREAD|DEBUG)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(interaction_id|rms|peak|silence|threshold)\b", "", cleaned, flags=re.IGNORECASE)
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
        
        if self.llm_enabled:
            try:
                model_name = "qwen:latest"
                if self._config is not None:
                    model_name = self._config.get("llm.model", model_name)
                client = ollama.Client(host='http://127.0.0.1:11434')
                client.generate(model=model_name, prompt='hi', stream=False)
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
            self._last_stt_metrics = {
                "text_len": len(text),
                "duration_s": duration_s,
                "rms": rms,
                "peak": peak,
                "silence_ratio": silence_ratio,
                "confidence": confidence_proxy,
            }
            return text
        except Exception as e:
            self.logger.error(f"[STT] Failed: {e}", exc_info=True)
            self._record_timeline("STT_ERROR", stage="stt", interaction_id=interaction_id)
            return ""

    def generate_response(self, text, interaction_id: str = ""):
        if not self.llm_enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""
        mode = self._resolve_personality_mode()
        serious_mode = self._is_serious(text)
        prompt = self._build_llm_prompt(text, mode, serious_mode)
        self.logger.info(f"[LLM] Prompt: '{text}'")
        full_response = ""
        try:
            model_name = "qwen:latest"
            if self._config is not None:
                model_name = self._config.get("llm.model", model_name)
            client = ollama.Client(host='http://127.0.0.1:11434')
            self._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
            start = time.perf_counter()
            first_token_ms = None
            stream = client.generate(model=model_name, prompt=prompt, stream=True)
            
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
            full_response = self._strip_prompt_artifacts(full_response)
            self.logger.info(f"[LLM] Response: '{full_response[:60]}...'")
            return full_response
        except Exception as e:
            self.logger.error(f"[LLM] Error: {e}")
            self._record_timeline("LLM_ERROR", stage="llm", interaction_id=interaction_id)
            return "[Error connecting to LLM]"

    def set_llm_enabled(self, enabled: bool) -> None:
        self.llm_enabled = bool(enabled)

    def _resolve_personality_mode(self) -> str:
        try:
            mode = self.runtime_overrides.get("personality_mode")
            if not mode and self._config is not None:
                mode = self._config.get("personality.mode", "mild")
        except Exception:
            mode = "mild"
        return mode or "mild"

    def _is_serious(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        return any(kw in lower for kw in self._serious_mode_keywords)

    def _build_llm_prompt(self, user_text: str, mode: str, serious_mode: bool) -> str:
        critical = "CRITICAL: Never use numbered lists or bullet points. Use plain conversational prose only.\n"
        if serious_mode:
            persona = (
                "You are ARGO in SERIOUS_MODE.\n"
                "Tone: clean, calm, surgical. No jokes. No sarcasm.\n"
                "Give a direct answer, then a brief explanation.\n"
                "No fluff. No theatrics. No filler.\n"
            )
        elif mode == "tommy_gunn":
            persona = (
                "You are ARGO in TOMMY GUNN MODE (Dry, Smart, Amused).\n"
                "Tone: sharp, well-read adult. Dry and observational. Calm confidence.\n"
                "Required flow: Dry hook (1 sentence) → Direct factual correction → Plain explanation → Wry observation on myth origin → Authority close.\n"
                "No greetings. No questions at the end unless user explicitly asked for follow-ups.\n"
                "Humor: one dry jab max, must not add new info. If in doubt, remove it.\n"
                "Metaphors optional, brief, grounded. No stacked metaphors.\n"
                "SERIOUS_MODE: drop humor entirely, skip dry hook, deliver facts cleanly and directly.\n"
                "Do NOT output section labels (e.g., 'Dry hook:', 'Direct factual correction:', 'Plain explanation:', 'Wry observation:', 'Authority close:').\n"
                "Do NOT repeat system instructions or flags like SERIOUS_MODE or CRITICAL.\n"
                "No corporate filler. No therapy talk. No 'as an AI' phrasing.\n"
                "Never include system diagnostics in responses.\n"
            )
        else:
            persona = (
                "You are ARGO, a veteran mentor.\n"
                "You speak clearly, confidently, and with quiet humor.\n"
                "Start with a direct observation or conclusion.\n"
                "Explain only what matters.\n"
                "End with a line that adds perspective or a small smile.\n"
                "Do not perform, hype, or explain yourself.\n"
            )
        return f"{persona}{critical}User: {user_text}\nResponse:"

    def _strip_prompt_artifacts(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"\bSERIOUS_MODE\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCRITICAL\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        labels = [
            r"dry hook",
            r"direct factual correction",
            r"plain explanation",
            r"wry observation",
            r"authority close",
        ]
        for label in labels:
            text = re.sub(rf"\b{label}\b\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text

    def _build_count_response(self, text: str) -> str:
        target = self._parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def _parse_count_target(self, text: str) -> int:
        if not text:
            return 5
        match = re.search(r"\b(\d+)\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 5
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        for word, value in words.items():
            if re.search(rf"\b{word}\b", text, flags=re.IGNORECASE):
                return value
        return 5

    def _format_system_health(self, health: dict) -> str:
        return (
            f"CPU at {health.get('cpu_percent')} percent. "
            f"Memory at {health.get('ram_percent')} percent. "
            f"Disk {health.get('disk_percent')} percent full."
        )

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        text = (
            f"Your system has {total_gb} gigabytes of memory installed. "
            f"Currently using about {used_pct} percent."
        )
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            text += f" CPU temperature is {cpu_temp} degrees."
        if gpu_temp is not None:
            text += f" GPU temperature is {gpu_temp} degrees."
        return text

    def _format_temperature_response(self, temps: dict) -> str:
        parts = []
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            parts.append(f"CPU temperature is {cpu_temp} degrees.")
        if gpu_temp is not None:
            parts.append(f"GPU temperature is {gpu_temp} degrees.")
        if not parts:
            return "Temperature sensors are not available on this system."
        return " ".join(parts) + " Normal."

    def _format_system_full_report(self, report: dict) -> str:
        health = report.get("health", {}) or {}
        disks = report.get("disks", {}) or {}
        uptime_seconds = report.get("uptime_seconds", 0) or 0
        network = report.get("network", []) or []
        battery = report.get("battery")
        fans = report.get("fans")

        parts = []
        cpu_pct = health.get("cpu_percent")
        ram_pct = health.get("ram_percent")
        disk_pct = health.get("disk_percent")
        gpu_pct = health.get("gpu_percent")
        gpu_mem = health.get("gpu_mem_percent")
        if cpu_pct is not None and ram_pct is not None and disk_pct is not None:
            parts.append(f"CPU is {cpu_pct} percent. Memory is {ram_pct} percent. Disk usage is {disk_pct} percent.")
        if gpu_pct is not None:
            if gpu_mem is not None:
                parts.append(f"GPU usage is {gpu_pct} percent, with VRAM at {gpu_mem} percent.")
            else:
                parts.append(f"GPU usage is {gpu_pct} percent.")

        cpu_temp = health.get("cpu_temp")
        gpu_temp = health.get("gpu_temp")
        if cpu_temp is not None or gpu_temp is not None:
            temp_bits = []
            if cpu_temp is not None:
                temp_bits.append(f"CPU {cpu_temp}°C")
            if gpu_temp is not None:
                temp_bits.append(f"GPU {gpu_temp}°C")
            parts.append("Temperatures: " + ", ".join(temp_bits) + ".")

        if uptime_seconds:
            hours = round(uptime_seconds / 3600, 1)
            parts.append(f"Uptime is {hours} hours.")

        if disks:
            disk_bits = []
            for label, info in sorted(disks.items()):
                drive_label = label.replace(":", "")
                free_text = self._format_size_gb(info["free_gb"])
                total_text = self._format_size_gb(info["total_gb"])
                disk_bits.append(
                    f"{drive_label} drive is {info['percent']} percent full, with {free_text} free out of {total_text}."
                )
            parts.append("Drives: " + " ".join(disk_bits))

        if network:
            net_bits = []
            for nic in network:
                label = nic.get("name")
                ip = nic.get("ip")
                speed = nic.get("speed_mbps")
                seg = label or "Network"
                if ip:
                    seg += f" {ip}"
                if speed:
                    seg += f" {speed}Mbps"
                net_bits.append(seg)
            parts.append("Network: " + ", ".join(net_bits) + ".")

        if battery:
            pct = battery.get("percent")
            plugged = battery.get("plugged")
            if pct is not None:
                status = "plugged in" if plugged else "on battery"
                parts.append(f"Battery is {pct} percent, {status}.")

        if fans:
            fan_bits = [f"{f['label']} {f['rpm']}RPM" for f in fans if f.get("rpm") is not None]
            if fan_bits:
                parts.append("Fans: " + ", ".join(fan_bits) + ".")

        if not parts:
            return "Hardware information unavailable."

        return "System status. " + " ".join(parts)

    def _format_size_gb(self, gb: float) -> str:
        try:
            if gb >= 1024:
                tb = round(gb / 1024, 2)
                return f"{tb} terabytes"
            gigs = int(gb)
            megs = int(round((gb - gigs) * 1024))
            if gigs > 0 and megs > 0:
                return f"{gigs} gigs {megs} megs"
            if gigs > 0:
                return f"{gigs} gigs"
            return f"{megs} megs"
        except Exception:
            return f"{gb} gigs"

    def _strip_disallowed_phrases(self, text: str) -> str:
        if not text:
            return text
        phrases = [
            "I'm sorry",
            "I cannot provide",
            "you may want to consult",
        ]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        filtered = [s for s in sentences if not any(p.lower() in s.lower() for p in phrases)]
        cleaned = " ".join(filtered).strip()
        return cleaned

    def speak(self, text, interaction_id: str = ""):
        if not self.runtime_overrides.get("tts_enabled", True):
            self.logger.info("[TTS] Disabled by runtime override")
            return
        self.logger.info(f"[TTS] Speaking with {self.current_voice_key}...")
        if self.current_state == "TRANSCRIBING":
            self.transition_state("THINKING", interaction_id=interaction_id, source="tts")
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
                    # Use os.set_blocking if available, else fallback for cross-platform
                    try:
                        set_blocking = getattr(os, "set_blocking", None)
                        if set_blocking:
                            set_blocking(self.tts_process.stdout.fileno(), False)
                        else:
                            if sys.platform != "win32":
                                try:
                                    import fcntl
                                    getfl = getattr(fcntl, "F_GETFL", None)
                                    setfl = getattr(fcntl, "F_SETFL", None)
                                    nonblock = getattr(os, "O_NONBLOCK", 0)
                                    if getfl is not None and setfl is not None:
                                        flags = fcntl.fcntl(self.tts_process.stdout.fileno(), getfl)
                                        if nonblock:
                                            fcntl.fcntl(self.tts_process.stdout.fileno(), setfl, flags | nonblock)
                                except Exception:
                                    pass
                    except Exception as e:
                        self.logger.warning(f"[TTS] Could not set non-blocking mode: {e}")
            except Exception:
                pass
            if self.tts_process.stdin:
                try:
                    self.tts_process.stdin.write((text or "").encode('utf-8'))
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
                except Exception as e:
                    self.logger.error(f"[TTS] Exception during audio read: {e}")
                    break
                if data:
                    try:
                        self.audio.play_chunk(np.frombuffer(data, dtype='int16'))
                    except Exception as e:
                        self.logger.error(f"[TTS] Exception during play_chunk: {e}")
                        break
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
            try:
                self.audio.release_audio("TTS", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[TTS] Exception during audio.release_audio: {e}")
            self.is_speaking = False
            self._record_timeline("TTS_DONE", stage="tts", interaction_id=interaction_id)


    def _classify_canonical_topic(self, user_text):
        """
        Deterministically classify user_text into canonical topic buckets.
        Returns (topic, matched_keywords) or (None, set())
        """
        from core.intent_parser import (
            detect_system_health,
            detect_disk_query,
            detect_temperature_query,
            HARDWARE_KEYWORDS,
            SYSTEM_OS_QUERIES,
            SYSTEM_MEMORY_QUERIES,
            SYSTEM_CPU_QUERIES,
            SYSTEM_GPU_QUERIES,
            SYSTEM_MOTHERBOARD_QUERIES,
        )
        text = user_text.lower() if user_text else ""
        tokens = set(re.findall(r"\w+", text))

        # SYSTEM_HEALTH short-circuit (must be evaluated before SELF_IDENTITY)
        health_matches = set()
        if detect_system_health(text):
            health_matches.add("system_health")
        if detect_disk_query(text):
            health_matches.add("disk")
        if detect_temperature_query(text):
            health_matches.add("temperature")
        for kw in HARDWARE_KEYWORDS:
            if kw in text:
                health_matches.add(kw)
        for q in SYSTEM_OS_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MEMORY_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_CPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_GPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MOTHERBOARD_QUERIES:
            if q in text:
                health_matches.add(q)
        if tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"}:
            health_matches |= (tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"})
        if health_matches:
            return "SYSTEM_HEALTH", health_matches

        # COUNT short-circuit (numeric/utility before other canonical topics)
        count_number_tokens = {
            "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        }
        if ("count" in tokens and ("to" in tokens or tokens & count_number_tokens or re.search(r"\b\d+\b", text))):
            return "COUNT", {"count"}
        topic_keywords = {
            "LAW": {"law", "laws", "rule", "rules", "constraint", "constraints", "policy", "policies", "govern", "governing"},
            "GATES": {"gate", "gates", "permission", "permissions", "barrier", "barriers", "check", "checks"},
            # Removed 'system' from ARCHITECTURE keywords to allow 'system health' etc. to route to normal logic
            "ARCHITECTURE": {"architecture", "design", "pipeline", "structure", "modules", "components", "layout", "engine"},
            "SELF_IDENTITY": {"identity", "yourself", "argo", "agent", "assistant", "name"},
            "CAPABILITIES": {"capability", "capabilities", "can", "able", "features", "do", "function", "functions", "limit", "limits", "limitation", "limitations", "cannot", "not", "support", "supported"},
            "CODEBASE_STATS": set(),
        }
        # Priority order: LAW, GATES, ARCHITECTURE
        for topic in ["LAW", "GATES", "ARCHITECTURE"]:
            keywords = topic_keywords[topic]
            matched = tokens & keywords
            if matched:
                return topic, matched

        # CODEBASE_STATS explicit phrase matching only (avoid count-only triggers)
        codebase_phrases = {
            "codebase",
            "code base",
            "codebase stats",
            "repo stats",
            "repository stats",
            "workspace stats",
            "project stats",
            "workspace size",
            "repo size",
            "repository size",
            "lines of code",
            "python files",
            "file count",
            "files in workspace",
            "files in the workspace",
        }
        matched_codebase = {p for p in codebase_phrases if p in text}
        if matched_codebase:
            return "CODEBASE_STATS", matched_codebase

        # CAPABILITIES before SELF_IDENTITY fallback
        keywords = topic_keywords["CAPABILITIES"]
        matched = tokens & keywords
        if matched:
            return "CAPABILITIES", matched

        # SELF_IDENTITY fallback (tightened)
        keywords = topic_keywords["SELF_IDENTITY"]
        matched = tokens & keywords
        identity_phrases = {
            "who are you",
            "what are you",
            "who is argo",
            "what is argo",
            "what is your name",
            "what's your name",
            "whats your name",
            "tell me about yourself",
            "tell me about you",
            "identify yourself",
            "who am i talking to",
            "who am i speaking to",
        }
        if any(p in text for p in identity_phrases):
            return "SELF_IDENTITY", {p for p in identity_phrases if p in text}
        identity_specific = tokens & {"argo", "yourself", "identity", "assistant", "agent", "name"}
        question_cue = tokens & {"who", "what"}
        if identity_specific and question_cue:
            return "SELF_IDENTITY", (identity_specific | question_cue)
        return None, set()

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
            user_text = normalize_system_text(user_text)

            # CANONICAL INTERCEPTION: Classify and intercept before any LLM routing
            from core.canonical_answers import get_canonical_answer
            topic, matched = self._classify_canonical_topic(user_text)
            if topic == "SYSTEM_HEALTH":
                self.logger.info(f"[CANONICAL] SYSTEM_HEALTH matched keywords: {sorted(matched)} | LLM BYPASSED")
                topic = None
            if topic == "COUNT":
                response = self._build_count_response(user_text)
                self.logger.info(f"[CANONICAL] Intercepted topic: COUNT | Matched: {sorted(matched)} | LLM BYPASSED")
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return
            if topic:
                answer = get_canonical_answer(topic)
                self.logger.info(f"[CANONICAL] Intercepted topic: {topic} | Matched: {sorted(matched)} | LLM BYPASSED")
                self.broadcast("log", f"Argo: {answer}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(answer or "")
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
            user_text_lower = user_text.lower()
            if any(term in user_text_lower for term in stop_terms):
                music_player = get_music_player()
                if music_player.is_playing():
                    self.logger.info("[ARGO] Active music detected")
                    music_player.stop()
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return
            stt_conf = 0.0
            try:
                stt_conf = float((self._last_stt_metrics or {}).get("confidence", 0.0))
            except Exception:
                stt_conf = 0.0
            if stt_conf < 0.35 or not user_text.strip():
                if is_system_keyword(user_text):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but whitelisted system intent: {user_text}")
                elif re.search(r"\bcount\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but count detected; continuing")
                elif any(term in user_text_lower for term in stop_terms):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but stop intent detected; continuing")
                elif stt_conf < 0.15 or not user_text.strip():
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) or empty text; skipping")
                    if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                        self.speak("I didn’t catch that clearly. Try saying it as a full sentence.", interaction_id=interaction_id)
                        self._low_conf_notice_given = True
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

            self.broadcast("log", f"User: {user_text}")


            intent = None
            try:
                intent = self._intent_parser.parse(user_text)
            except Exception:
                intent = None

            # --- MUSIC VOLUME CONTROL (voice) ---
            # Recognize patterns like 'music volume 75%', 'set volume to 50%', 'volume up', 'volume down'
            from core.music_player import set_volume_percent, adjust_volume_percent, get_volume_percent
            volume_patterns = [
                (r"(?:music )?volume (\d{1,3})%", lambda m: set_volume_percent(int(m.group(1)))),
                (r"set volume to (\d{1,3})%", lambda m: set_volume_percent(int(m.group(1)))),
                (r"volume up (\d{1,3})%", lambda m: adjust_volume_percent(int(m.group(1)))),
                (r"volume down (\d{1,3})%", lambda m: adjust_volume_percent(-int(m.group(1)))),
                (r"volume up", lambda m: adjust_volume_percent(10)),
                (r"volume down", lambda m: adjust_volume_percent(-10)),
                (r"what is the volume", lambda m: None),
                (r"current volume", lambda m: None),
            ]
            user_text_lower = user_text.lower().strip()
            for pat, action in volume_patterns:
                m = re.fullmatch(pat, user_text_lower)
                if m:
                    if pat in ["what is the volume", "current volume"]:
                        vol = get_volume_percent()
                        response = f"Music volume: {vol}%"
                    else:
                        action(m)
                        vol = get_volume_percent()
                        response = f"Music volume set to {vol}%"
                    self.logger.info(f"[ARGO] {response}")
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    self.logger.info("--- Interaction Complete ---")
                    self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                    return

            if intent and intent.intent_type in {
                IntentType.MUSIC,
                IntentType.MUSIC_STOP,
                IntentType.MUSIC_NEXT,
                IntentType.MUSIC_STATUS,
            }:
                if not self.runtime_overrides.get("music_enabled", True):
                    msg = "Music is disabled."
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak(msg, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                music_player = get_music_player()
                blocked = music_player.preflight()
                if blocked:
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("Music library not indexed yet.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return
                playback_started = False
                error_message = ""

                if intent.intent_type == IntentType.MUSIC_STOP:
                    music_player.stop()
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("Stopped.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                if intent.intent_type == IntentType.MUSIC_NEXT:
                    playback_started = music_player.play_next(None)
                    if not playback_started:
                        error_message = "No music playing."

                elif intent.intent_type == IntentType.MUSIC_STATUS:
                    status = query_music_status()
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak(status, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                else:
                    artist = getattr(intent, "artist", None)
                    title = getattr(intent, "title", None)
                    do_not_try_genre_lookup = bool(title)
                    explicit_genre = bool(getattr(intent, "explicit_genre", False))
                    if getattr(intent, "is_generic_play", False) and not artist and not title and not getattr(intent, "keyword", None):
                        playback_started = music_player.play_random(None)
                        if not playback_started:
                            error_message = "Your music library is empty or unavailable."
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        return
                    if title:
                        playback_started = music_player.play_by_song(title, None)
                        if not playback_started and not artist:
                            playback_started = music_player.play_by_artist(title, None)
                    if not playback_started and artist:
                        playback_started = music_player.play_by_artist(artist, None)
                    if not playback_started and getattr(intent, "keyword", None):
                        keyword = intent.keyword
                        if explicit_genre and not do_not_try_genre_lookup:
                            playback_started = music_player.play_by_genre(keyword, None)
                        if not playback_started:
                            playback_started = music_player.play_by_keyword(keyword, None)
                        if not playback_started:
                            error_message = f"No music found for '{keyword}'."
                    if not playback_started and not artist and not title and not getattr(intent, "keyword", None):
                        playback_started = music_player.play_random(None)
                        if not playback_started:
                            error_message = "No music available."

                if intent.intent_type == IntentType.MUSIC and not playback_started and title:
                    setattr(intent, "unresolved", True)
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("I can’t find that track in your library.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                if error_message and self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                    self.speak(error_message, interaction_id=interaction_id)

                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return

            if intent and intent.intent_type == IntentType.COUNT:
                response = self._build_count_response(user_text)
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            if intent and intent.intent_type == IntentType.SYSTEM_HEALTH:
                subintent = getattr(intent, "subintent", None)
                raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
                if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
                    disks = get_disk_info()
                    if not disks:
                        response = "Hardware information unavailable."
                    else:
                        drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
                        if not drive_match:
                            drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
                        if drive_match:
                            letter = drive_match.group(1).upper()
                            key = f"{letter}:"
                            info = disks.get(key) or disks.get(letter)
                            if info:
                                response = (
                                    f"{letter} drive is {info['percent']} percent full, "
                                    f"with {info['free_gb']} gigabytes free."
                                )
                            else:
                                response = "Hardware information unavailable."
                        elif "fullest" in raw_text_lower or "most used" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                            response = f"{disk} is the fullest drive at {info['percent']} percent used."
                        elif "most free" in raw_text_lower or "most space" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                            response = f"{disk} has the most free space at {info['free_gb']} gigabytes free."
                        else:
                            total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
                            response = f"You have {total_free} gigabytes free across {len(disks)} drives."
                elif subintent == "full":
                    report = get_system_full_report()
                    response = self._format_system_full_report(report)
                elif subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
                    profile = get_system_profile()
                    gpus = get_gpu_profile()
                    raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
                    wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
                    if subintent == "memory":
                        ram_gb = profile.get("ram_gb") if profile else None
                        if wants_specs and profile:
                            speed = profile.get("memory_speed_mhz")
                            modules = profile.get("memory_modules")
                            extra = []
                            if speed:
                                extra.append(f"{speed}MHz")
                            if modules:
                                extra.append(f"{modules} modules")
                            extra_text = f" ({', '.join(extra)})" if extra else ""
                            response = f"Your system has {ram_gb} gigabytes of memory{extra_text}."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your system has {ram_gb} gigabytes of memory."
                            if ram_gb is not None
                            else "Hardware information unavailable."
                        )
                    elif subintent == "cpu":
                        cpu_name = profile.get("cpu") if profile else None
                        if wants_specs and profile:
                            cores = profile.get("cpu_cores")
                            threads = profile.get("cpu_threads")
                            mhz = profile.get("cpu_max_mhz")
                            maker = profile.get("cpu_manufacturer")
                            bits = []
                            if maker:
                                bits.append(maker)
                            if cores:
                                bits.append(f"{cores} cores")
                            if threads:
                                bits.append(f"{threads} threads")
                            if mhz:
                                bits.append(f"{mhz} MHz max")
                            detail = f" ({', '.join(bits)})" if bits else ""
                            response = f"Your CPU is a {cpu_name}{detail}." if cpu_name else "Hardware information unavailable."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your CPU is a {cpu_name}."
                            if cpu_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "gpu":
                        if gpus:
                            if wants_specs:
                                gpu_bits = []
                                for gpu in gpus:
                                    name = gpu.get("name")
                                    vram = gpu.get("vram_mb")
                                    dv = gpu.get("driver_version")
                                    detail = []
                                    if vram:
                                        detail.append(f"{vram}MB VRAM")
                                    if dv:
                                        detail.append(f"driver {dv}")
                                    gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                                response = "Your GPU(s): " + "; ".join(gpu_bits) + "."
                                self.broadcast("log", f"Argo: {response}")
                                if not self.stop_signal.is_set() and not replay_mode:
                                    tts_text = self._sanitize_tts_text(response)
                                    tts_override = (overrides or {}).get("suppress_tts", False)
                                    if tts_override:
                                        self.logger.info("[TTS] Suppressed for next interaction override")
                                    elif tts_text:
                                        self.speak(tts_text, interaction_id=interaction_id)
                                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                                self.logger.info("--- Interaction Complete ---")
                                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                                return
                            response = f"Your GPU is {gpus[0].get('name')}."
                        else:
                            response = "No GPU detected."
                    elif subintent == "os":
                        os_name = profile.get("os") if profile else None
                        response = (
                            f"You are running {os_name}."
                            if os_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "motherboard":
                        board = profile.get("motherboard") if profile else None
                        if wants_specs and profile:
                            bios = profile.get("bios_version")
                            sys_maker = profile.get("system_manufacturer")
                            sys_model = profile.get("system_model")
                            parts = []
                            if sys_maker or sys_model:
                                parts.append(" ".join(p for p in [sys_maker, sys_model] if p))
                            if bios:
                                parts.append(f"BIOS {bios}")
                            extra = f" ({', '.join(parts)})" if parts else ""
                            response = f"Your motherboard is {board}{extra}." if board else "Hardware information unavailable."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your motherboard is {board}."
                            if board
                            else "Hardware information unavailable."
                        )
                    else:
                        cpu_name = profile.get("cpu") if profile else None
                        ram_gb = profile.get("ram_gb") if profile else None
                        gpu_name = gpus[0].get("name") if gpus else None
                        if not cpu_name or ram_gb is None:
                            response = "Hardware information unavailable."
                        else:
                            response = (
                                f"Your CPU is a {cpu_name}. "
                                f"You have {ram_gb} gigabytes of memory."
                            )
                            if gpu_name:
                                response += f" Your GPU is {gpu_name}."
                            if wants_specs and profile:
                                drives = profile.get("storage_drives") or []
                                if drives:
                                    drive_bits = []
                                    for d in drives:
                                        name = d.get("model") or "Drive"
                                        size = d.get("size_gb")
                                        iface = d.get("interface")
                                        detail = []
                                        if size:
                                            detail.append(f"{size}GB")
                                        if iface:
                                            detail.append(iface)
                                        drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                                    response += " Storage: " + "; ".join(drive_bits) + "."
                elif subintent == "temperature":
                    temps = get_temperature_health()
                    if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                        response = "Temperature sensors are not available on this system."
                    else:
                        response = self._format_temperature_response(temps)
                else:
                    health = get_system_health()
                    self.logger.info(
                        "[SYSTEM] cpu=%s ram=%s disk=%s",
                        health.get("cpu_percent"),
                        health.get("ram_percent"),
                        health.get("disk_percent"),
                    )
                    response = self._format_system_health(health)
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            if intent and intent.intent_type == IntentType.SYSTEM_INFO:
                profile = get_system_profile()
                gpus = get_gpu_profile()
                subintent = getattr(intent, "subintent", None)
                if subintent == "memory":
                    ram_gb = profile.get("ram_gb") if profile else None
                    response = (
                        f"Your system has {ram_gb} gigabytes of memory."
                        if ram_gb is not None
                        else "Hardware information unavailable."
                    )
                elif subintent == "cpu":
                    cpu_name = profile.get("cpu") if profile else None
                    response = (
                        f"Your CPU is a {cpu_name}."
                        if cpu_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "gpu":
                    if gpus:
                        response = f"Your GPU is {gpus[0].get('name')}."
                    else:
                        response = "No GPU detected."
                elif subintent == "os":
                    os_name = profile.get("os") if profile else None
                    response = (
                        f"You are running {os_name}."
                        if os_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "motherboard":
                    board = profile.get("motherboard") if profile else None
                    response = (
                        f"Your motherboard is {board}."
                        if board
                        else "Hardware information unavailable."
                    )
                else:
                    response = "Hardware information unavailable."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
            ai_text = self.generate_response(user_text, interaction_id=interaction_id)
            ai_text = re.sub(r"[^\x00-\x7F]+", "", ai_text or "")
            ai_text = self._strip_disallowed_phrases(ai_text)
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
