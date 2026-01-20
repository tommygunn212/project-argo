"""
COORDINATOR v4: INTERACTION LOOP + SESSION MEMORY (BOUNDED & CONTROLLED)

Orchestration layer that loops for multiple interactions with short-term working memory.

Pipeline (repeats per iteration):
1. InputTrigger: Wait for wake word
2. Audio Capture: Record user speech
3. SpeechToText: Transcribe to text
4. IntentParser: Classify text to intent
5. ResponseGenerator: Generate response via LLM (with optional memory reference)
6. OutputSink: Speak response
7. SessionMemory: Store interaction (utterance, intent, response)
8. Check stop condition (user said "stop" OR max interactions reached)

Loop continues UNTIL:
- User says a stop command ("stop", "goodbye", etc.)
- OR max interactions reached (hardcoded: e.g., 3)
- Then exit cleanly

This is pure orchestration. Coordinator does NOT know or care that ResponseGenerator uses an LLM.

Core concept:
- InputTrigger: Detects wake word, fires callback
- SpeechToText: Transcribes audio to text
- IntentParser: Classifies text into intent
- ResponseGenerator: Generates response text (LLM-based, isolated)
- OutputSink: Generates audio from text, publishes it
- SessionMemory: Stores recent interactions (bounded ring buffer)
- Coordinator: Orchestrates them in correct order, loops until stop condition

SessionMemory:
- Stores last N interactions (default 3)
- Cleared on program exit (not persistent)
- Read-only for ResponseGenerator (can reference but not modify)
- Automatically evicts oldest when full
- NOT learning, NOT embeddings, NOT personality

Changes from v3:
- Add SessionMemory instantiation at startup
- Append to memory after each iteration
- Pass SessionMemory to ResponseGenerator (read-only)
- Clear memory on exit
- Everything else identical to v3

What Coordinator is NOT:
- Not a brain (no logic beyond routing)
- Not intelligent (purely orchestration)
- Not knowledgeable (ResponseGenerator is isolated)
- Not configurable (hardcoded everything)
- Not persistent (SessionMemory cleared on exit)
- Not fault-tolerant (no retries)
- Not a full chatbot (short-term working memory only, not personality)

This is controlled, bounded orchestration with short-term scratchpad memory.
"""

import logging
from typing import Optional
from datetime import datetime
import sounddevice as sd
import numpy as np
from core.session_memory import SessionMemory
from core.latency_probe import LatencyProbe, LatencyStats

# === Logging ===
logger = logging.getLogger(__name__)


class Coordinator:
    """
    End-to-end orchestration with bounded interaction loop + session memory.
    
    Loop behavior (v4 — differs from v3):
    - Repeats until STOP condition
    - Each iteration is independent (no learning, no personality)
    - Short-term working memory stores recent interactions
    - SessionMemory passed to ResponseGenerator (read-only)
    - Exits cleanly after stop or max iterations
    
    Stop conditions:
    1. User says a stop command (detected in response text)
    2. Max interactions reached (hardcoded)
    
    SessionMemory:
    - Bounded ring buffer (default capacity 3)
    - Stores: utterance, intent, response per interaction
    - Read-only for ResponseGenerator (can reference recent context)
    - Cleared automatically on exit (not persistent)
    - NOT embeddings, NOT learning, NOT personality
    
    Each iteration:
    1. Wait for wake word (InputTrigger)
    2. Record audio during trigger callback
    3. Transcribe audio (SpeechToText)
    4. Classify intent (IntentParser)
    5. Generate response (ResponseGenerator, with SessionMemory available)
    6. Speak response (OutputSink)
    7. Store in SessionMemory (utterance, intent, response)
    8. Check stop condition
    9. If no stop → loop back to step 1
    10. If stop → clear memory and exit cleanly
    
    What Coordinator does:
    - Loop until stop condition
    - Orchestrate all layers in correct order per iteration
    - Record audio window during callback
    - Route text through SpeechToText → IntentParser
    - Pass intent + SessionMemory to ResponseGenerator for response
    - Call OutputSink to speak
    - Append interaction to SessionMemory
    - Track interaction count
    - Detect stop keywords in response
    - Clear memory on exit
    - Exit cleanly when done
    
    What Coordinator does NOT:
    - Inspect or modify generated response text (except for stop detection)
    - Know that ResponseGenerator uses an LLM
    - Modify SessionMemory (append-only, read-only for generator)
    - Make responses learn or adapt (each response independent)
    - Retry on failure (single attempt per turn)
    - Make any decisions beyond routing
    
    v4 Changes from v3:
    - Add SessionMemory instantiation at startup
    - Append to memory after each iteration
    - Pass SessionMemory to ResponseGenerator
    - Clear memory on exit
    - Everything else identical to v3
    
    Multi-turn with working memory but stateless personality:
    wake → listen → respond → [store in memory] → [check stop] → [loop] → exit
    
    Usage:
    ```python
    coordinator = Coordinator(
        input_trigger=trigger,
        speech_to_text=stt,
        intent_parser=parser,
        response_generator=generator,
        output_sink=sink
    )
    coordinator.run()  # Loops until stop condition or max interactions
    ```
    """
    
    # Audio recording parameters
    AUDIO_DURATION = 6  # seconds (after wake word) - DEPRECATED, use dynamic recording
    AUDIO_SAMPLE_RATE = 16000  # Hz
    MAX_RECORDING_DURATION = 15  # seconds max (safety limit)
    SILENCE_DURATION = 1.5  # seconds of silence to stop recording
    SILENCE_THRESHOLD = 500  # audio level below this = silence (RMS)
    
    # Loop control (hardcoded)
    MAX_INTERACTIONS = 3  # Max interactions per session
    STOP_KEYWORDS = ["stop", "goodbye", "quit", "exit"]  # Stop command keywords
    
    def __init__(self, input_trigger, speech_to_text, intent_parser, response_generator, output_sink):
        """
        Initialize Coordinator with all pipeline layers + SessionMemory.
        
        Args:
            input_trigger: InputTrigger instance (detects wake word)
            speech_to_text: SpeechToText instance (transcribes audio)
            intent_parser: IntentParser instance (classifies text)
            response_generator: ResponseGenerator instance (generates response)
            output_sink: OutputSink instance (speaks response)
        """
        self.trigger = input_trigger
        self.stt = speech_to_text
        self.parser = intent_parser
        self.generator = response_generator
        self.sink = output_sink
        self.logger = logger
        
        # Audio buffer for recording
        self.recorded_audio = None
        
        # Session memory (v4) — short-term working memory for this session only
        self.memory = SessionMemory(capacity=3)
        
        # TASK 15: Latency instrumentation
        self.latency_stats = LatencyStats()
        self.current_probe: Optional[LatencyProbe] = None
        
        # PHASE 16: Observer snapshot state (for read-only observation)
        self._last_wake_timestamp = None
        self._last_transcript = None
        self._last_intent = None
        self._last_response = None
        
        # TASK 17: Half-duplex audio gate (prevent simultaneous listen/speak)
        self._is_speaking = False
        
        # Loop state (v3)
        self.interaction_count = 0
        self.stop_requested = False
        
        self.logger.info("[Coordinator v4] Initialized (with interaction loop + session memory)")
        self.logger.debug(f"  InputTrigger: {type(self.trigger).__name__}")
        self.logger.debug(f"  SpeechToText: {type(self.stt).__name__}")
        self.logger.debug(f"  IntentParser: {type(self.parser).__name__}")
        self.logger.debug(f"  ResponseGenerator: {type(self.generator).__name__}")
        self.logger.debug(f"  OutputSink: {type(self.sink).__name__}")
        self.logger.debug(f"  SessionMemory: capacity={self.memory.capacity}")
        self.logger.debug(f"  Max interactions: {self.MAX_INTERACTIONS}")
        self.logger.debug(f"  Stop keywords: {self.STOP_KEYWORDS}")
    
    def run(self) -> None:
        """
        Run bounded interaction loop with session memory.
        
        Behavior (v4 — differs from v3):
        - Loop until stop condition or max interactions
        - Each iteration: wake → record → transcribe → parse → generate → speak → store
        - After each iteration: check for stop keyword or max reached
        - SessionMemory passed to ResponseGenerator (read-only)
        - SessionMemory cleared on exit
        - If no stop → loop back to waiting for wake word
        - If stop → exit cleanly
        
        Stop conditions:
        1. Response text contains stop keyword ("stop", "goodbye", "quit", "exit")
        2. Max interactions reached (hardcoded: MAX_INTERACTIONS)
        
        Each iteration:
        1. Wait for wake word (blocking)
        2. Record audio (3-5 seconds)
        3. Transcribe to text (Whisper)
        4. Parse to intent (rules-based)
        5. Generate response (LLM, with SessionMemory available)
        6. Speak response (TTS)
        7. Store in SessionMemory (utterance, intent, response)
        8. Check stop condition
        9. If no stop → continue loop
        10. If stop → break loop
        
        SessionMemory behavior:
        - Append each interaction (utterance, intent, response)
        - Only recent N interactions stored (default 3)
        - Oldest entries automatically evicted when full
        - Cleared on exit (not persistent)
        - ResponseGenerator can read but not modify
        
        This is a blocking call. It loops until stop condition, then returns.
        """
        self.logger.info("[run] Starting Coordinator v4 (interaction loop + session memory)...")
        self.logger.info(f"[run] Max interactions: {self.MAX_INTERACTIONS}")
        self.logger.info(f"[run] Stop keywords: {self.STOP_KEYWORDS}")
        self.logger.info(f"[run] SessionMemory capacity: {self.memory.capacity}")
        
        try:
            # Loop until stop condition
            while True:
                self.interaction_count += 1
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"[Loop] Iteration {self.interaction_count}/{self.MAX_INTERACTIONS}")
                self.logger.info(f"[Loop] Memory: {self.memory}")
                self.logger.info(f"{'='*60}")
                
                try:
                    # TASK 15: Initialize latency probe for this interaction
                    self.current_probe = LatencyProbe(self.interaction_count)
                    
                    # Define callback: when trigger fires, record → transcribe → parse → generate → speak → store
                    def on_trigger_detected():
                        self.logger.info(f"[Iteration {self.interaction_count}] Wake word detected!")
                        
                        # TASK 15: Mark wake detection
                        self.current_probe.mark("wake_detected")
                        
                        try:
                            # 1. Record audio with dynamic silence detection
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Recording (max {self.MAX_RECORDING_DURATION}s, stops on {self.SILENCE_DURATION}s silence)..."
                            )
                            
                            # TASK 15: Mark recording start
                            self.current_probe.mark("recording_start")
                            
                            # Record audio dynamically with silence detection
                            audio = self._record_with_silence_detection()
                            
                            # TASK 15: Mark recording end
                            self.current_probe.mark("recording_end")
                            
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Recorded {len(audio)} samples ({len(audio)/self.AUDIO_SAMPLE_RATE:.2f}s)"
                            )
                            
                            # Convert to WAV bytes
                            from scipy.io import wavfile
                            import io
                            
                            audio_buffer = io.BytesIO()
                            wavfile.write(audio_buffer, self.AUDIO_SAMPLE_RATE, audio)
                            audio_bytes = audio_buffer.getvalue()
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Audio buffer: {len(audio_bytes)} bytes"
                            )
                            
                            # 2. Transcribe audio
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Transcribing audio..."
                            )
                            
                            # TASK 15: Mark STT start
                            self.current_probe.mark("stt_start")
                            
                            text = self.stt.transcribe(audio_bytes, self.AUDIO_SAMPLE_RATE)
                            
                            # TASK 15: Mark STT end
                            self.current_probe.mark("stt_end")
                            
                            # PHASE 16: Capture for observer snapshot
                            self._last_wake_timestamp = datetime.now()
                            self._last_transcript = text
                            
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Transcribed: '{text}'"
                            )
                            
                            # Skip if transcription is empty (just silence/noise)
                            if not text or not text.strip():
                                self.logger.info(
                                    f"[Iteration {self.interaction_count}] "
                                    f"Empty transcription (silence only), skipping..."
                                )
                                return
                            
                            # 3. Parse intent
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Parsing intent..."
                            )
                            
                            # TASK 15: Mark parsing start
                            self.current_probe.mark("parsing_start")
                            
                            intent = self.parser.parse(text)
                            
                            # TASK 15: Mark parsing end
                            self.current_probe.mark("parsing_end")
                            
                            # PHASE 16: Capture for observer snapshot
                            self._last_intent = intent
                            
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Intent: {intent.intent_type.value} "
                                f"(confidence={intent.confidence:.2f})"
                            )
                            
                            # 4. Generate response (LLM, with SessionMemory available)
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Generating response..."
                            )
                            
                            # TASK 15: Mark LLM start
                            self.current_probe.mark("llm_start")
                            
                            # Check if this is a music command (before LLM processing)
                            from core.intent_parser import IntentType
                            if intent.intent_type == IntentType.MUSIC:
                                # Music playback
                                from core.music_player import get_music_player
                                music_player = get_music_player()
                                music_player.play_random(self.sink)
                                response_text = ""  # No LLM response for music
                                self.current_probe.mark("llm_end")
                            else:
                                # Normal LLM response
                                response_text = self.generator.generate(intent, self.memory)
                                self.current_probe.mark("llm_end")
                            
                            # PHASE 16: Capture for observer snapshot
                            self._last_response = response_text
                            
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Response: '{response_text}'"
                            )
                            
                            # 5. Speak response (with interrupt-on-voice support)
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Speaking response..."
                            )
                            
                            # TASK 15: Mark TTS start
                            self.current_probe.mark("tts_start")
                            
                            # Only speak if response is not empty (music playback has empty response)
                            if response_text and response_text.strip():
                                # TASK 17: Set speaking flag (half-duplex audio gate)
                                self._is_speaking = True
                                try:
                                    # Speak and monitor for user interrupt (voice input during playback)
                                    self._speak_with_interrupt_detection(response_text)
                                finally:
                                    self._is_speaking = False
                            else:
                                self.logger.info(
                                    f"[Iteration {self.interaction_count}] "
                                    f"Response is empty, skipping TTS"
                                )
                            
                            # TASK 15: Mark TTS end
                            self.current_probe.mark("tts_end")
                            
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Response spoken"
                            )
                            
                            # 6. Store in SessionMemory (v4)
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Storing in memory..."
                            )
                            self.memory.append(
                                user_utterance=text,
                                parsed_intent=intent.intent_type.value,
                                generated_response=response_text
                            )
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] "
                                f"Memory updated: {self.memory}"
                            )
                            
                            # 7. Check for stop keyword in response
                            response_lower = response_text.lower()
                            for keyword in self.STOP_KEYWORDS:
                                if keyword in response_lower:
                                    self.logger.info(
                                        f"[Iteration {self.interaction_count}] "
                                        f"Stop keyword detected: '{keyword}'"
                                    )
                                    self.stop_requested = True
                                    break
                            
                            # TASK 15: Log interaction latency and add to stats
                            self.current_probe.log_summary()
                            self.latency_stats.add_probe(self.current_probe)
                            
                        except Exception as e:
                            self.logger.error(
                                f"[Iteration {self.interaction_count}] Failed: {e}"
                            )
                            raise
                    
                    # Block waiting for trigger (each iteration waits for wake word)
                    # TASK 17: Skip listening if currently speaking (half-duplex audio gate)
                    if self._is_speaking:
                        self.logger.info(
                            f"[Iteration {self.interaction_count}] "
                            f"Skipping wake word detection (currently speaking)"
                        )
                        return
                    
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] "
                        f"Listening for wake word..."
                    )
                    self.trigger.on_trigger(on_trigger_detected)
                    
                    # on_trigger() returns after callback completes
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] "
                        f"Interaction complete"
                    )
                    
                    # Check loop exit conditions
                    if self.stop_requested:
                        self.logger.info(f"[Loop] Stop requested by user")
                        break
                    
                    if self.interaction_count >= self.MAX_INTERACTIONS:
                        self.logger.info(
                            f"[Loop] Max interactions ({self.MAX_INTERACTIONS}) reached"
                        )
                        break
                    
                    # Otherwise, continue loop
                    self.logger.info(
                        f"[Loop] Continuing... "
                        f"({self.MAX_INTERACTIONS - self.interaction_count} "
                        f"interactions remaining)"
                    )
                
                except Exception as e:
                    self.logger.error(
                        f"[Iteration {self.interaction_count}] Failed: {e}"
                    )
                    raise
            
            # Loop exited (either stop keyword or max interactions)
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"[Loop] Exiting after {self.interaction_count} interaction(s)")
            if self.stop_requested:
                self.logger.info(f"[Loop] Reason: User requested stop")
            else:
                self.logger.info(f"[Loop] Reason: Max interactions reached")
            
            # Clear memory on exit (v4)
            self.logger.info(f"[Loop] Clearing SessionMemory...")
            self.memory.clear()
            self.logger.info(f"[Loop] SessionMemory cleared: {self.memory}")
            
            # TASK 15: Log aggregated latency report
            self.logger.info(f"{'='*60}")
            self.latency_stats.log_report()
            self.logger.info(f"{'='*60}\n")
            
            self.logger.info("[run] Coordinator v4 complete")
        
        except Exception as e:
            self.logger.error(f"[run] Failed: {e}")
            # Clear memory even on error
            self.memory.clear()
            raise
    
    def _record_with_silence_detection(self) -> np.ndarray:
        """
        Record audio with dynamic silence detection.
        
        Stops recording when:
        1. Silence (low audio level) detected for SILENCE_DURATION seconds, OR
        2. MAX_RECORDING_DURATION reached (safety limit)
        
        Returns:
            numpy array of int16 audio samples at AUDIO_SAMPLE_RATE Hz
        """
        import numpy as np
        
        # Chunk size for processing (100ms)
        chunk_samples = int(self.AUDIO_SAMPLE_RATE * 0.1)
        silence_samples_threshold = int(self.AUDIO_SAMPLE_RATE * self.SILENCE_DURATION)
        max_samples = int(self.AUDIO_SAMPLE_RATE * self.MAX_RECORDING_DURATION)
        
        audio_buffer = []
        consecutive_silence_samples = 0
        total_samples = 0
        
        try:
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
            )
            stream.start()
            
            while total_samples < max_samples:
                # Read one chunk
                chunk, _ = stream.read(chunk_samples)
                if chunk.size == 0:
                    break
                
                audio_buffer.append(chunk)
                total_samples += chunk.shape[0]
                
                # Check for silence (RMS < threshold)
                rms = np.sqrt(np.mean(chunk.astype(float) ** 2))
                
                if rms < self.SILENCE_THRESHOLD:
                    consecutive_silence_samples += chunk.shape[0]
                else:
                    # Audio detected, reset silence counter
                    consecutive_silence_samples = 0
                
                # Stop if enough silence detected
                if consecutive_silence_samples >= silence_samples_threshold:
                    self.logger.info(
                        f"[Record] Silence detected, stopping recording "
                        f"({total_samples/self.AUDIO_SAMPLE_RATE:.2f}s recorded)"
                    )
                    break
            
            stream.stop()
            stream.close()
        
        except Exception as e:
            self.logger.error(f"[Record] Error during audio recording: {e}")
            raise
        
        # Concatenate all chunks
        if audio_buffer:
            return np.concatenate(audio_buffer, axis=0)
        else:
            return np.array([], dtype=np.int16)
    
    def _speak_with_interrupt_detection(self, response_text: str) -> None:
        """
        Speak response with interrupt detection.
        
        Detects if user speaks (wakes word or voice detected) while TTS is playing.
        If interrupt detected, stops TTS immediately and restarts listening loop.
        
        Args:
            response_text: Text to speak
        """
        import threading
        import time
        import asyncio
        
        interrupt_detected = False
        monitor_interval = 0.2  # Check every 200ms
        
        def speak_sync():
            """Run speak in thread so we can monitor it."""
            self.sink.speak(response_text)
        
        try:
            # Start TTS in background thread
            speak_thread = threading.Thread(target=speak_sync, daemon=True)
            speak_thread.start()
            
            # Initialize Porcupine for interrupt detection
            from core.input_trigger import PorcupineWakeWordTrigger
            interrupt_detector = PorcupineWakeWordTrigger()
            
            self.logger.info("[Interrupt] Monitoring for user input during playback...")
            
            # Poll for interrupt while TTS is playing
            while speak_thread.is_alive():
                try:
                    # Quick check for wake word or voice activity
                    if interrupt_detector._check_for_interrupt():
                        interrupt_detected = True
                        self.logger.warning("[Interrupt] User interrupted! Stopping TTS...")
                        
                        # Stop the TTS audio playback (async call in sync context)
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(self.sink.stop())
                            else:
                                loop.run_until_complete(self.sink.stop())
                        except Exception as e:
                            self.logger.debug(f"[Interrupt] Could not stop sink: {e}")
                        
                        break
                except Exception as e:
                    # Silently continue monitoring on error
                    self.logger.debug(f"[Interrupt] Check failed: {e}")
                
                time.sleep(monitor_interval)
            
            # Wait for speak thread to finish (or timeout if interrupted)            speak_thread.join(timeout=30)
            
            if interrupt_detected:
                self.logger.info("[Interrupt] TTS interrupted by user")
        
        except Exception as e:
            self.logger.error(f"[Interrupt] Error during interrupt detection: {e}")