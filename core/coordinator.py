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
import threading
from typing import Optional
from datetime import datetime
import sounddevice as sd
import numpy as np
from core.intent_parser import IntentType
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
    AUDIO_SAMPLE_RATE = 16000  # Hz
    MAX_RECORDING_DURATION = 15.0  # seconds max (safety net) — Extended for longer LED explanation
    MIN_RECORDING_DURATION = 0.9  # Minimum record duration (prevents truncation)
    SILENCE_DURATION = 1.2  # Seconds of silence to stop recording — TUNED for fast response
    MINIMUM_RECORD_DURATION = 0.9  # Minimum record duration (prevents truncation) - CANONICAL NAME
    SILENCE_TIMEOUT_SECONDS = 3.0  # Seconds of silence to stop recording — Allows time to think
    SILENCE_THRESHOLD = 100  # Audio level below this = silence (RMS absolute) — Increased to ignore breathing pauses
    RMS_SPEECH_THRESHOLD = 0.003  # RMS normalized level (0-1) to START silence timer — More lenient threshold
    PRE_ROLL_BUFFER_MS_MIN = 1000  # Min milliseconds of pre-speech audio to capture — 1 second pre-wake context
    PRE_ROLL_BUFFER_MS_MAX = 1200  # Max milliseconds to keep in rolling buffer — 1.2 second look-back
    
    # Debug/profiling flags
    RECORD_DEBUG = False  # Set to True for detailed recording metrics (or via env var)
    
    # Loop control (hardcoded)
    MAX_INTERACTIONS = 10  # Max interactions per session — Increased for longer testing
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
        import os
        from core.command_executor import CommandExecutor
        
        self.trigger = input_trigger
        self.stt = speech_to_text
        self.parser = intent_parser
        self.generator = response_generator
        self.sink = output_sink
        self.logger = logger
        
        # CommandExecutor for procedural commands (count to N, etc.)
        self.executor = CommandExecutor(audio_sink=output_sink)
        
        # Enable debug metrics via env var or class flag
        self.record_debug = os.getenv("ARGO_RECORD_DEBUG", "0").lower() in ("1", "true")
        
        # Audio buffer for recording
        self.recorded_audio = None
        
        # Session memory (v4) — short-term working memory for this session only
        self.memory = SessionMemory(capacity=1)
        
        # TASK 15: Latency instrumentation
        self.latency_stats = LatencyStats()
        self.current_probe: Optional[LatencyProbe] = None
        
        # PHASE 16: Observer snapshot state (for read-only observation)
        self._last_wake_timestamp = None
        self._last_transcript = None
        self._last_intent = None
        self._last_response = None
        
        # TASK 17: Half-duplex audio gate (prevent simultaneous listen/speak)
        # Use threading.Event for thread-safe atomic state (not boolean)
        self._is_speaking = threading.Event()
        self._is_speaking.clear()  # Initially not speaking
        
        # Debug/profiling flag from environment (can override class default)
        self.record_debug = os.getenv("RECORD_DEBUG", "").lower() == "true" or self.RECORD_DEBUG
        
        # GUI Callbacks (optional, can be set by external GUI)
        self.on_recording_start = None
        self.on_recording_stop = None
        self.on_status_update = None
        
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
                # Flag to track if this iteration is a music command (doesn't count as interaction)
                is_music_iteration = False
                
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
                            
                            # GUI Callback: Recording started
                            if self.on_recording_start:
                                try:
                                    self.on_recording_start()
                                except Exception as e:
                                    self.logger.debug(f"[Coordinator] on_recording_start callback error: {e}")
                            
                            # Record audio dynamically with silence detection
                            audio = self._record_with_silence_detection()
                            
                            # TASK 15: Mark recording end
                            self.current_probe.mark("recording_end")
                            
                            # GUI Callback: Recording stopped
                            if self.on_recording_stop:
                                try:
                                    self.on_recording_stop()
                                except Exception as e:
                                    self.logger.debug(f"[Coordinator] on_recording_stop callback error: {e}")
                            
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
                            
                            # 4. Check procedural commands FIRST (before LLM generation)
                            # Procedural commands must execute immediately without LLM latency
                            
                            # Check if this is a procedural command (count to N, etc.)
                            if self.executor.can_execute(text):
                                self.logger.info(f"[Iteration {self.interaction_count}] Procedural command detected: '{text}'")
                                # TASK 15: Mark LLM start (skip for procedural commands)
                                self.current_probe.mark("llm_start")
                                try:
                                    # Execute command directly (bypasses LLM)
                                    self.executor.execute(text)
                                    response_text = ""  # No LLM response for procedural commands
                                    self.current_probe.mark("llm_end")
                                    # Exit callback - procedural command complete, skip LLM
                                    self.logger.info(f"[Iteration {self.interaction_count}] Procedural command complete")
                                    return
                                except Exception as e:
                                    self.logger.error(f"[Iteration {self.interaction_count}] Procedural command failed: {e}")
                                    response_text = "Command failed."
                                    self.current_probe.mark("llm_end")
                                    return
                            
                            # Generate response (LLM, with SessionMemory available)
                            self.logger.info(
                                f"[Iteration {self.interaction_count}] Generating response..."
                            )
                            
                            # TASK 15: Mark LLM start
                            self.current_probe.mark("llm_start")
                            
                            # Check if this is a STOP command (highest priority - short-circuit)
                            if intent.intent_type == IntentType.MUSIC_STOP:
                                self.logger.info(f"[Iteration {self.interaction_count}] STOP command: Stopping music")
                                from core.music_player import get_music_player
                                music_player = get_music_player()
                                music_player.stop()
                                
                                # Optional brief response
                                self.sink.speak("Stopped.")
                                response_text = ""
                                self.current_probe.mark("llm_end")
                                # Exit callback - continue to next iteration (outer loop)
                                return
                            
                            # Check if this is a NEXT command (highest priority - short-circuit)
                            if intent.intent_type == IntentType.MUSIC_NEXT:
                                self.logger.info(f"[Iteration {self.interaction_count}] NEXT command: Playing next track")
                                from core.music_player import get_music_player
                                music_player = get_music_player()
                                
                                playback_started = music_player.play_next(self.sink)
                                if not playback_started:
                                    self.sink.speak("No music playing.")
                                    self.logger.warning(f"[Iteration {self.interaction_count}] NEXT failed: no playback mode")
                                else:
                                    self.logger.info(f"[Iteration {self.interaction_count}] NEXT: Started playback")
                                    # Monitor for interrupt during music playback
                                    self._monitor_music_interrupt(music_player)
                                
                                response_text = ""
                                self.current_probe.mark("llm_end")
                                # Exit callback - continue to next iteration (outer loop)
                                return
                            
                            # Check if this is a STATUS query (read-only - no side effects)
                            if intent.intent_type == IntentType.MUSIC_STATUS:
                                self.logger.info(f"[Iteration {self.interaction_count}] STATUS query: What's playing")
                                from core.music_status import query_music_status
                                
                                status = query_music_status()
                                self.sink.speak(status)
                                self.logger.info(f"[Iteration {self.interaction_count}] STATUS response: {status}")
                                
                                response_text = ""
                                self.current_probe.mark("llm_end")
                                # Exit callback - continue to next iteration (outer loop)
                                return
                            
                            # Check if this is a music command (before LLM processing)
                            if intent.intent_type == IntentType.MUSIC:
                                # Music playback with STRICT priority routing
                                # IMPORTANT: Music commands don't count as conversational turns
                                is_music_iteration = True
                                self.logger.info(f"[Iteration {self.interaction_count}] Music command - not counting as interaction turn")
                                
                                from core.music_player import get_music_player
                                music_player = get_music_player()
                                
                                playback_started = False
                                error_message = ""
                                
                                if intent.keyword:
                                    keyword = intent.keyword
                                    self.logger.info(f"[Iteration {self.interaction_count}] Music keyword: '{keyword}'")
                                    
                                    # PRIORITY ORDER (FIXED):
                                    # 1. Exact artist match
                                    if not playback_started:
                                        playback_started = music_player.play_by_artist(keyword, None)  # No sink here
                                        if playback_started:
                                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: ARTIST match")
                                    
                                    # 2. Exact song match
                                    if not playback_started:
                                        playback_started = music_player.play_by_song(keyword, None)  # No sink here
                                        if playback_started:
                                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: SONG match")
                                    
                                    # 3. Genre match (with adjacent fallback)
                                    if not playback_started:
                                        playback_started = music_player.play_by_genre(keyword, None)  # No sink here
                                        if playback_started:
                                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: GENRE match")
                                    
                                    # 4. Keyword token match
                                    if not playback_started:
                                        playback_started = music_player.play_by_keyword(keyword, None)  # No sink here
                                        if playback_started:
                                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: KEYWORD match")
                                    
                                    # 5. Random fallback
                                    if not playback_started:
                                        playback_started = music_player.play_random(None)  # No sink here
                                        if playback_started:
                                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: RANDOM fallback")
                                    
                                    # If still no playback, consolidate error into single message
                                    if not playback_started:
                                        error_message = f"No music found for '{keyword}'."
                                        self.logger.warning(f"[Iteration {self.interaction_count}] Music failed: {error_message}")
                                else:
                                    # No keyword: random track
                                    self.logger.info(f"[Iteration {self.interaction_count}] Music route: RANDOM (no keyword)")
                                    playback_started = music_player.play_random(None)  # No sink here
                                    if not playback_started:
                                        error_message = "No music available."
                                        self.logger.warning(f"[Iteration {self.interaction_count}] Music failed: {error_message}")
                                
                                response_text = ""  # No LLM response for music
                                
                                # Speak error message only once (if no playback started)
                                if error_message and not playback_started:
                                    self.sink.speak(error_message)
                                
                                # Monitor for interrupt during music playback
                                if playback_started:
                                    self.logger.info(f"[Iteration {self.interaction_count}] Monitoring for interrupt during music...")
                                    self._monitor_music_interrupt(music_player)
                                
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
                                self._is_speaking.set()
                                try:
                                    # Speak and monitor for user interrupt (voice input during playback)
                                    self._speak_with_interrupt_detection(response_text)
                                finally:
                                    self._is_speaking.clear()
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
                    
                    # If this was a music iteration, decrement the counter (music doesn't count)
                    if is_music_iteration:
                        self.interaction_count -= 1
                        self.logger.info(
                            f"[Iteration] Music iteration complete - decremented counter to {self.interaction_count}"
                        )
                    
                    # Block waiting for trigger (each iteration waits for wake word)
                    # TASK 17: Skip listening if currently speaking (half-duplex audio gate)
                    if self._is_speaking.is_set():
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
                    
                    # Check if max interactions reached
                    if self.interaction_count >= self.MAX_INTERACTIONS:
                        # CRITICAL: Don't exit while music is playing
                        # Music lifecycle must outlive coordinator loop
                        try:
                            from core.music_player import get_music_player
                            music_player = get_music_player()
                            if music_player.is_playing:
                                self.logger.info(
                                    f"[Loop] Max interactions reached, but music is playing - continuing loop"
                                )
                                # Don't break - let music keep playing
                                # Wait for next wake word (or silence timeout)
                                self.logger.info(
                                    f"[Loop] Waiting for next command or music to finish..."
                                )
                            else:
                                # Music not playing, safe to exit
                                self.logger.info(
                                    f"[Loop] Max interactions ({self.MAX_INTERACTIONS}) reached"
                                )
                                break
                        except Exception as e:
                            self.logger.warning(f"[Loop] Could not check music status: {e} - exiting")
                            break
                    else:
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
    
    def stop(self) -> None:
        """Stop the coordinator loop gracefully."""
        self.logger.info("[stop] Stop requested via stop() method")
        self.stop_requested = True
    
    def _record_with_silence_detection(self) -> np.ndarray:
        """
        Record audio with dynamic silence detection and pre-roll buffer.
        
        Enhanced recording logic:
        1. Prepend pre-roll buffer (speech onset captured before wake word)
        2. Enforce minimum record duration (0.9s)
        3. Start silence timer only after speech energy detected (RMS > threshold)
        4. Stop on silence (2.2s) or max duration (15s)
        5. Emit debug metrics (gated by RECORD_DEBUG flag)
        
        Returns:
            numpy array of int16 audio samples at AUDIO_SAMPLE_RATE Hz
        """
        import numpy as np
        import time
        
        # Chunk size for processing (100ms)
        chunk_samples = int(self.AUDIO_SAMPLE_RATE * 0.1)
        min_samples = int(self.AUDIO_SAMPLE_RATE * self.MINIMUM_RECORD_DURATION)
        silence_samples_threshold = int(self.AUDIO_SAMPLE_RATE * self.SILENCE_TIMEOUT_SECONDS)
        max_samples = int(self.AUDIO_SAMPLE_RATE * self.MAX_RECORDING_DURATION)
        
        audio_buffer = []
        consecutive_silence_samples = 0
        total_samples = 0
        speech_detected = False
        speech_detected_at = None
        silence_started_at = None
        stop_reason = None
        rms_samples = []  # For calculating average RMS (debug metric)
        
        # Get pre-roll buffer from trigger (speech onset before wake word)
        preroll_frames = []
        try:
            preroll_frames = self.trigger.get_preroll_buffer()
        except Exception as e:
            self.logger.debug(f"[Record] Could not retrieve pre-roll buffer: {e}")
        
        # Prepend pre-roll buffer to audio
        if preroll_frames:
            for frame in preroll_frames:
                audio_buffer.append(frame)
                total_samples += frame.shape[0]
            if self.record_debug:
                self.logger.info(f"[Record] Pre-roll: {len(preroll_frames)} frames ({total_samples/self.AUDIO_SAMPLE_RATE:.2f}s)")
        
        recording_start_time = time.time()
        stream = None
        try:
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
            )
            stream.start()
            
            rms = 0.0  # Initialize before loop (defensive: prevents UnboundLocalError in logging)
            
            while total_samples < max_samples:
                # Read one chunk
                chunk, _ = stream.read(chunk_samples)
                if chunk.size == 0:
                    break
                
                audio_buffer.append(chunk)
                total_samples += chunk.shape[0]
                elapsed_time = time.time() - recording_start_time
                
                # Calculate RMS for this chunk (normalized 0-1)
                rms = np.sqrt(np.mean(chunk.astype(float) ** 2)) / 32768.0  # Normalize int16 range
                rms_samples.append(rms)
                
                # Detect speech (RMS > threshold) — only start silence timer after speech detected
                if not speech_detected and rms > self.RMS_SPEECH_THRESHOLD:
                    speech_detected = True
                    speech_detected_at = elapsed_time
                    if self.record_debug:
                        rms_str = f"{rms:.4f}" if rms is not None else "N/A"
                        self.logger.info(f"[Record] Speech detected at {elapsed_time:.3f}s (RMS={rms_str})")
                
                # Track silence only after speech has been detected
                if speech_detected:
                    if rms < self.SILENCE_THRESHOLD:
                        if silence_started_at is None:
                            silence_started_at = elapsed_time
                        consecutive_silence_samples += chunk.shape[0]
                    else:
                        # Audio detected, reset silence counter
                        consecutive_silence_samples = 0
                        silence_started_at = None
                    
                    # Stop if enough silence detected AND minimum duration reached
                    if (consecutive_silence_samples >= silence_samples_threshold and
                        total_samples >= min_samples):
                        stop_reason = "silence"
                        if self.record_debug:
                            silence_duration = elapsed_time - silence_started_at if silence_started_at else 0
                            self.logger.info(
                                f"[Record] Silence detected ({silence_duration:.2f}s >= {self.SILENCE_TIMEOUT_SECONDS}s), "
                                f"stopping recording ({total_samples/self.AUDIO_SAMPLE_RATE:.2f}s recorded)"
                            )
                        break
                
                # Also stop if max duration reached
                if total_samples >= max_samples:
                    stop_reason = "max_duration"
                    # Guard formatting (belt + suspenders: logging must never crash)
                    avg_rms = np.mean(rms_samples) if rms_samples else 0.0
                    avg_rms_str = f"{avg_rms:.2f}" if avg_rms is not None else "N/A"
                    self.logger.warning(
                        f"[Record] MAX DURATION REACHED (15.0s) - stopping recording | "
                        f"total_samples={total_samples}, avg_rms={avg_rms_str}"
                    )
                    break
        
        except Exception as e:
            self.logger.error(f"[Record] Error during audio recording: {e}")
            raise
        
        finally:
            # Guarantee stream cleanup even on exception or cancellation
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    self.logger.warning(f"[Record] Error closing stream: {e}")
        
        # Emit debug metrics (gated by RECORD_DEBUG flag)
        if self.record_debug and rms_samples:
            avg_rms = np.mean(rms_samples)
            avg_rms_str = f"{avg_rms:.4f}" if avg_rms is not None else "N/A"
            self.logger.info(f"[Record] Recording Summary:")
            self.logger.info(f"  Duration: {total_samples/self.AUDIO_SAMPLE_RATE:.2f}s (minimum: {self.MINIMUM_RECORD_DURATION}s)")
            self.logger.info(f"  RMS average: {avg_rms_str} (normalized 0-1, threshold: {self.RMS_SPEECH_THRESHOLD})")
            self.logger.info(f"  Speech detected at: {speech_detected_at:.3f}s" if speech_detected_at else "  Speech: NOT detected")
            self.logger.info(f"  Stop reason: {stop_reason}")
            self.logger.info(f"  Silence threshold: {self.SILENCE_THRESHOLD} (absolute RMS)")
            self.logger.info(f"  Silence timeout: {self.SILENCE_TIMEOUT_SECONDS}s")
            if self._last_transcript:
                self.logger.info(f"  Transcript: '{self._last_transcript}'")
        
        # Concatenate all chunks
        if audio_buffer:
            return np.concatenate(audio_buffer, axis=0)
        else:
            return np.array([], dtype=np.int16)
    
    def _monitor_music_interrupt(self, music_player) -> None:
        """
        Monitor for user interrupt during music playback.
        
        If user speaks/wakes word detected, stop music immediately.
        
        IMPORTANT: Reuses existing trigger instance (self.trigger) instead of
        creating a new PorcupineWakeWordTrigger to avoid re-initialization overhead.
        
        Args:
            music_player: MusicPlayer instance to stop on interrupt
        """
        import time
        
        try:
            self.logger.info("[Music] Monitoring for interrupt...")
            
            # Poll while music is playing
            while music_player.is_playing:
                try:
                    # Reuse existing trigger instance to check for interrupt
                    if self.trigger._check_for_interrupt():
                        self.logger.warning("[Music] User interrupted! Stopping music...")
                        music_player.stop()
                        break
                except Exception as e:
                    self.logger.debug(f"[Music] Interrupt check failed: {e}")
                
                time.sleep(0.2)  # Check every 200ms
        
        except Exception as e:
            self.logger.error(f"[Music] Monitor error: {e}")

    
    def _speak_with_interrupt_detection(self, response_text: str) -> None:
        """
        Speak response WITHOUT interrupt detection (Option A: simplest).
        
        Argo should NOT interrupt itself during TTS playback.
        This matches standard assistant behavior (Alexa, Siri, Google Assistant).
        
        Runs TTS in main thread (blocking).
        Disables interrupt monitoring during playback to prevent Argo self-interruption.
        Re-enables after playback finishes.
        
        Args:
            response_text: Text to speak
        """
        try:
            self.logger.info("[TTS] Speaking response (interrupts disabled during playback)...")
            
            # Speak in main thread (blocking, event loop-safe)
            # IMPORTANT: Do NOT monitor for interrupts while Argo is speaking
            # This prevents Argo from interrupting itself with its own audio
            self.sink.speak(response_text)
            
            self.logger.info("[TTS] Response finished")
        
        except Exception as e:
            self.logger.error(f"[TTS] Error during speech: {e}")
        
        finally:
            # Ensure speaking flag is cleared even if exception occurred
            self._is_speaking.clear()
