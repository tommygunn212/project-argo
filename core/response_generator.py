"""
Response Generator Module

Responsibility: Convert Intent → Response String (with optional context from SessionMemory)
Nothing more.

Does NOT:
- Access audio
- Access triggers
- Control flow
- Call OutputSink or SpeechToText (except optional sentence streaming when enabled)
- Maintain memory (SessionMemory is read-only input)
- Store internal state
- Modify SessionMemory
- Retry on failure
- Stream output (single response only)

This is where the LLM lives. Isolated. Contained. Labeled.

v4 Update:
- Accepts optional SessionMemory for context reference
- Can include recent interactions in prompt
- Never modifies memory
- Memory is read-only scratchpad

v5 Update:
- Example-driven personality injection
- Two modes: Mild (default) + Claptrap (explicit only)
- Personality loaded via examples, not heuristics
"""

from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Optional
from core.config import ENABLE_LLM_TTS_STREAMING, get_config
from core.policy import LLM_TIMEOUT_SECONDS, LLM_WATCHDOG_SECONDS, WATCHDOG_FALLBACK_RESPONSE
from core.watchdog import Watchdog
from core.output_sink import get_output_sink

# Minimal stop-word list for semantic overlap guard
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "to", "of",
    "in", "on", "for", "it", "this", "that", "as", "with", "have",
    "has", "be", "by", "was", "were", "i", "you", "they", "we",
    "he", "she", "not", "do", "does", "did", "what", "why", "how",
}

# === Logging ===
logger = logging.getLogger(__name__)


class ResponseGenerator(ABC):
    """
    Base class for response generation engines.
    
    Single responsibility: Convert Intent → Response string
    
    v4 Update: Optionally accepts SessionMemory for context reference
    - memory is read-only (never modified)
    - can reference recent interactions in prompt
    - explicit and visible in code
    """

    @abstractmethod
    def generate(self, intent, memory: Optional['SessionMemory'] = None) -> str:
        """
        Generate a response for the given intent.

        Args:
            intent: Intent object with:
                - intent_type (IntentType enum)
                - confidence (float 0.0-1.0)
                - raw_text (str: original user input)
            memory: Optional SessionMemory for context reference (read-only)

        Returns:
            Response string (plain text, no markdown, no special formatting)

        Raises:
            ValueError: If intent is invalid or None
        """
        pass


class LLMResponseGenerator(ResponseGenerator):
    """
    LLM-based response generator using local Qwen model.
    
    Hardcoded model + parameters for predictability:
    - Model: argo:latest (Qwen via Ollama)
    - Temperature: 0.7 (deterministic but creative)
    - Max tokens: 100 (keep responses short)
    - No streaming (single response)
    - Read-only memory access (can reference, never modify)
    - No tool calling
    - No function calling
    
    v4 Update:
    - Accepts optional SessionMemory for context
    - May reference recent interactions in prompt
    - Never modifies memory
    - Memory is explicit and visible
    """

    def __init__(self):
        """Initialize LLM connection."""
        try:
            import requests
        except ImportError:
            raise ImportError("requests not installed. Run: pip install requests")

        self.requests = requests
        
        # Hardcoded LLM endpoint
        self.ollama_url = "http://localhost:11434"
        self.model = "argo:latest"
        
        # Hardcoded generation parameters
        self.temperature = 0.85  # Increased for more personality and creativity (0.7 was too dry)
        self.max_tokens = 2000  # Plenty of room for full answers (2-3 min speech worth)
        
        # Personality injection (example-driven)
        from core.personality import get_personality_loader
        self.personality_loader = get_personality_loader()
        self.personality_mode = "mild"  # Default mode
        
        self.logger = logger
        self.logger.info("[LLMResponseGenerator v5] Initialized")
        self.logger.debug(f"  Endpoint: {self.ollama_url}")
        self.logger.debug(f"  Model: {self.model}")
        self.logger.debug(f"  Temperature: {self.temperature}")
        self.logger.debug(f"  Max tokens: {self.max_tokens}")
        self.logger.debug(f"  Personality mode: {self.personality_mode}")
        # Transient last response for single-process correction inheritance
        self._last_response: Optional[str] = None
        # Transient uncommitted command candidate (text)
        self._uncommitted_command: Optional[str] = None
        # Feature flag (default off)
        try:
            config = get_config()
            self._enable_tts_streaming = bool(
                config.get("llm.enable_tts_streaming", ENABLE_LLM_TTS_STREAMING)
            )
        except Exception:
            self._enable_tts_streaming = ENABLE_LLM_TTS_STREAMING
        # Streaming output tracker (per call)
        self._streamed_output = False

    def generate(self, intent, memory: Optional['SessionMemory'] = None) -> str:
        """
        Generate a response using Qwen LLM with optional context from memory.

        Args:
            intent: Intent object (from IntentParser)
            memory: Optional SessionMemory for context (read-only)

        Returns:
            Response string generated by LLM

        Raises:
            ValueError: If intent is invalid
            RuntimeError: If LLM connection fails
        """
        if intent is None:
            raise ValueError("intent is None")

        # Extract intent information
        intent_type = intent.intent_type.value  # "greeting", "question", etc.
        raw_text = intent.raw_text  # Original user input
        confidence = intent.confidence

        # === Correction Inheritance (Rule 1) ===
        # If the user issues a short corrective utterance (or known correction phrase)
        # and there is a previous explanatory response in memory, adapt that response
        # directly (summarize/simplify/reframe) and return it. No clarification asked.
        try:
            # === Rule 3: Command Commitment Boundary (pre-dispatch guard) ===
            # If there is an uncommitted command candidate from a prior turn,
            # decide whether to abort, commit, or continue depending on current input.
            if self._uncommitted_command is not None:
                lt = raw_text.strip().lower()
                abort_phrases = ("never mind", "actually never mind", "stop", "no", "cancel")
                # Silence or ellipsis counts as abort
                if lt == "" or lt == "…" or lt == "..." or lt in abort_phrases:
                    self.logger.info("[generate] Uncommitted command aborted by user input")
                    self._uncommitted_command = None
                    return "Okay, canceled."
                # If current input is not a command (new question or correction unrelated), abort
                if intent_type != "command":
                    self.logger.info("[generate] Uncommitted command aborted due to non-command follow-up")
                    self._uncommitted_command = None
                    return "Okay, canceled."
                # If current input is a command and appears resolved (not ambiguous), commit and proceed
                # (do nothing here; later logic will generate the execution response)
        except Exception as e:
            self.logger.debug(f"[generate] Rule3 pre-dispatch check failed: {e}")

        try:
            have_prev = (memory is not None and not memory.is_empty()) or (self._last_response is not None)
            if have_prev:
                lt = raw_text.strip().lower()
                tokens = lt.split()
                is_short = len(tokens) <= 4
                # Known correction indicators
                correction_phrases = (
                    "no",
                    "no.",
                    "too long",
                    "too long.",
                    "that's not what i meant",
                    "thats not what i meant",
                    "try again",
                    "explain it simpler",
                    "explain it simpler.",
                    "that’s not what i meant",
                )

                is_correction = is_short or any(p in lt for p in correction_phrases)

                if is_correction:
                    if memory is not None and not memory.is_empty():
                        prev_intents = memory.get_recent_intents(1)
                        prev_responses = memory.get_recent_responses(1)
                    else:
                        prev_intents = []
                        prev_responses = [self._last_response] if self._last_response is not None else []

                    if prev_responses:
                        prev_intent = prev_intents[0] if prev_intents else ""
                        # Only apply if previous turn was not a command
                        if prev_intent.lower() != "command":
                            prev_response = prev_responses[0]
                            # === Scope guard: semantic overlap check ===
                            try:
                                # Tokenize and remove stop words
                                user_tokens = [t for t in re.findall(r"\w+", lt) if t not in STOP_WORDS]
                                prev_tokens = [t for t in re.findall(r"\w+", prev_response.lower()) if t not in STOP_WORDS]
                                overlap = set(user_tokens) & set(prev_tokens)
                                if not overlap:
                                    # No semantic overlap: skip correction inheritance and reset correction context
                                    self.logger.info("[generate] Correction inheritance skipped due to no semantic overlap")
                                    try:
                                        self._last_response = None
                                    except Exception:
                                        pass
                                    # Continue to normal generation flow
                                    raise StopIteration
                            except StopIteration:
                                pass
                            except Exception as e:
                                self.logger.debug(f"[generate] Overlap guard error: {e}")
                            # Decide adaptation mode
                            if "simpler" in lt or "too long" in lt:
                                mode = "simplify"
                            elif "not what" in lt or lt == "no" or "try again" in lt:
                                mode = "reframe"
                            elif is_short:
                                mode = "summarize"
                            else:
                                mode = "reframe"

                            prompt = (
                                f"User indicated a correction: '{raw_text}'.\n"
                                f"Please {mode} the previous assistant response below and produce a single committed answer (no clarification questions):\n\n"
                                f"Previous response: {prev_response}\n\nResponse:"
                            )

                            self.logger.info("[generate] Correction inheritance: adapting previous response (mode=%s)", mode)
                            # Call LLM directly to adapt previous response
                            response_text = self._call_llm(prompt)
                            response_text = self._enhance_response(response_text)
                            return response_text
        except Exception as e:
            self.logger.debug(f"[generate] Correction inheritance check failed: {e}")

        self.logger.info(
            f"[generate] Intent: {intent_type} "
            f"(confidence={confidence:.2f}, text='{raw_text[:50]}')"
        )

        # === Rule 2: One-shot Command Clarification ===
        # If intent is a command and appears ambiguous/underspecified,
        # ask one concise clarification (no polite fluff) and return it.
        # This implements the single-clarify-and-either-execute-or-abort behavior.
        try:
            if intent_type == "command":
                lt = raw_text.strip().lower()
                # Ambiguity heuristics (exact, short command forms)
                ambiguous_simple = (lt in ("play music", "play music.", "stop", "stop.", "next", "next."))
                open_photoshop_interrupt = "open photoshop" in lt and ("no wait" in lt or "…" in raw_text or "..." in raw_text)

                if ambiguous_simple or open_photoshop_interrupt:
                    # Mark this command as an uncommitted candidate and return concise clarification
                    self._uncommitted_command = raw_text
                    # Map concise clarifications per command type (wording must remain concise)
                    if "open photoshop" in lt:
                        return "Do you want me to open Photoshop or cancel?"
                    if lt.startswith("play music"):
                        return "Do you want me to play music now or pick a genre/device?"
                    if lt.startswith("stop"):
                        return "Stop everything or stop the current activity?"
                    if lt.startswith("next"):
                        return "Skip to the next item?"
                    # Fallback concise clarification
                    return "Do you want me to proceed or cancel?"
        except Exception as e:
            self.logger.debug(f"[generate] Rule2 check failed: {e}")
        
        # Log memory state if available (read-only inspection)
        if memory is not None:
            self.logger.debug(f"[generate] Memory available: {memory}")
            self.logger.debug(f"[generate] Recent interactions: {memory.get_recent_count()}")
        else:
            self.logger.debug(f"[generate] No memory available")

        # === Personality Injection (v5) ===
        # Check personality examples before calling LLM
        # Only applies to non-command intents (commands stay humor-free)
        if intent_type != "command":
            try:
                example = self.personality_loader.get_example(self.personality_mode, raw_text)
                if example:
                    self.logger.info(f"[generate] Personality match ({self.personality_mode}): returning example")
                    return example
            except Exception as e:
                self.logger.debug(f"[generate] Personality lookup failed: {e}")

        # Build prompt for LLM
        prompt = self._build_prompt(intent_type, raw_text, confidence, memory)
        self.logger.debug(f"[generate] Prompt: {prompt[:100]}...")

        # Call LLM
        try:
            response_text = self._call_llm(prompt)
            self.logger.info(f"[generate] Generated: '{response_text}'")
            # Store last response for possible correction-inheritance in subsequent turns
            try:
                self._last_response = response_text
            except Exception:
                pass
            return response_text

        except Exception as e:
            self.logger.error(f"[generate] LLM call failed: {e}")
            raise

    def _build_prompt(
        self,
        intent_type: str,
        raw_text: str,
        confidence: float,
        memory: Optional['SessionMemory'] = None
    ) -> str:
        """
        Build a prompt for the LLM based on intent and optional context.

        Args:
            intent_type: "greeting", "question", "command", "unknown"
            raw_text: Original user input
            confidence: Classification confidence
            memory: Optional SessionMemory for context (read-only)

        Returns:
            Prompt string for LLM
        """
        # Start with basic context from memory if available
        context = ""
        if memory is not None and not memory.is_empty():
            # Build context from recent interactions (read-only access)
            context_summary = memory.get_context_summary()
            if context_summary:
                context = f"Context from recent conversation:\n{context_summary}\n\n"
        
        # System personality: You are ARGO, a friendly and knowledgeable AI assistant.
        # You're conversational but intelligent, engaging but not verbose.
        # You explain things clearly with practical examples when useful.
        # You have personality without being over-the-top.
        
        # Different prompts based on intent type
        if intent_type == "greeting":
            prompt = (
                f"{context}"
                f"The user greeted you with: '{raw_text}'\n"
                f"You are ARGO, a friendly AI assistant. Respond with a warm, engaging greeting (one sentence).\n"
                f"Response:"
            )
        elif intent_type == "question":
            prompt = (
                f"{context}"
                f"The user asked: '{raw_text}'\n"
                f"You are ARGO. Answer the question thoroughly but conversationally. Aim for 2-3 sentences with clarity and depth.\n"
                f"If you don't know the answer, admit it honestly and suggest what they could try instead.\n"
                f"Response:"
            )
        elif intent_type == "music":
            # ZERO-LATENCY MUSIC-FIX: Explicit reminder about music player capability
            prompt = (
                f"{context}"
                f"The user asked to play music: '{raw_text}'\n"
                f"You are ARGO and you HAVE A MUSIC PLAYER ATTACHED. "
                f"Your job is to play music for them. "
                f"Extract the music genre or artist name from their request and play it enthusiastically.\n"
                f"Response:"
            )
        elif intent_type == "command":
            prompt = (
                f"{context}"
                f"The user gave a command: '{raw_text}'\n"
                f"You are ARGO. Execute the command directly with personality. If it's a count, list, recitation, or performance, do it enthusiastically.\n"
                f"Respond with the action itself, not just acknowledgment.\n"
                f"Response:"
            )
        else:  # unknown
            prompt = (
                f"{context}"
                f"The user said: '{raw_text}'\n"
                f"You didn't understand. Politely ask for clarification (one sentence max).\n"
                f"Response:"
            )

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """
        Call Qwen via Ollama endpoint.

        Args:
            prompt: Prompt string for LLM

        Returns:
            Generated response string

        Raises:
            RuntimeError: If connection fails or LLM returns error
        """
        try:
            # Reset streaming tracker per call
            self._streamed_output = False
            # Make request to Ollama
            url = f"{self.ollama_url}/api/generate"
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": bool(self._enable_tts_streaming),
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            }

            self.logger.debug(f"[_call_llm] Calling {url}")
            if self._enable_tts_streaming:
                self.logger.debug("[_call_llm] Streaming enabled")
                with Watchdog("LLM", LLM_WATCHDOG_SECONDS) as wd:
                    response = self.requests.post(
                        url, json=payload, timeout=LLM_TIMEOUT_SECONDS, stream=True
                    )

                    if response.status_code != 200:
                        raise RuntimeError(
                            f"LLM returned status {response.status_code}: {response.text}"
                        )

                    response_text = self._stream_llm_and_enqueue(response)

                if wd.triggered:
                    self.logger.warning("[WATCHDOG] LLM response exceeded watchdog; returning fallback response")
                    return WATCHDOG_FALLBACK_RESPONSE

                if not response_text:
                    raise RuntimeError("LLM returned empty response")

                # Enhance response quality
                response_text = self._enhance_response(response_text)

                return response_text

            # Non-streaming default (unchanged)
            with Watchdog("LLM", LLM_WATCHDOG_SECONDS) as wd:
                response = self.requests.post(url, json=payload, timeout=LLM_TIMEOUT_SECONDS)
            
            if response.status_code != 200:
                raise RuntimeError(
                    f"LLM returned status {response.status_code}: {response.text}"
                )

            # Parse response
            result = response.json()
            response_text = result.get("response", "").strip()

            if wd.triggered:
                self.logger.warning("[WATCHDOG] LLM response exceeded watchdog; returning fallback response")
                return WATCHDOG_FALLBACK_RESPONSE

            if not response_text:
                raise RuntimeError("LLM returned empty response")

            # Enhance response quality
            response_text = self._enhance_response(response_text)

            return response_text

        except self.requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Failed to connect to Ollama at {self.ollama_url}. "
                f"Make sure Ollama is running: {e}"
            )
        except Exception as e:
            raise RuntimeError(f"LLM call failed: {e}")

    def _stream_llm_and_enqueue(self, response) -> str:
        """
        Stream LLM output, enqueue complete sentences to TTS, and return full text.
        """
        self.logger.debug("[_stream_llm_and_enqueue] Streaming started")

        sink = None
        try:
            sink = get_output_sink()
        except Exception:
            sink = None

        buffer = ""
        full_response_parts = []
        first_sentence_enqueued = False

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except Exception:
                continue

            chunk = data.get("response", "")
            if chunk:
                buffer += chunk
                full_response_parts.append(chunk)

                sentences, buffer = self._extract_complete_sentences(buffer)
                for sentence in sentences:
                    self._enqueue_sentence(sink, sentence)
                    if not first_sentence_enqueued:
                        self.logger.debug("[_stream_llm_and_enqueue] First sentence enqueued")
                        first_sentence_enqueued = True

            if data.get("done"):
                break

        # Flush remaining partial sentence
        remaining = buffer.strip()
        if remaining:
            self._enqueue_sentence(sink, remaining)

        self.logger.debug("[_stream_llm_and_enqueue] Streaming complete")

        return "".join(full_response_parts).strip()

    def _extract_complete_sentences(self, text: str) -> tuple[list, str]:
        """
        Extract complete sentences from text buffer.
        Sentence boundary = ., ?, ! followed by whitespace.
        Returns (sentences, remainder).
        """
        sentences = []
        while True:
            match = re.search(r"[.!?]\s+", text)
            if not match:
                break
            cut = match.end()
            sentence = text[:cut].strip()
            if sentence:
                sentences.append(sentence)
            text = text[cut:]
        return sentences, text

    def _enqueue_sentence(self, sink, sentence: str) -> None:
        """
        Enqueue a sentence to the TTS queue without blocking.
        """
        if not sentence or not sentence.strip():
            return
        if sink is None or not hasattr(sink, "text_queue"):
            return
        try:
            sink.text_queue.put(sentence.strip())
            self._streamed_output = True
        except Exception:
            return
    def _enhance_response(self, response_text: str) -> str:
        """
        Post-process response to ensure quality and personality.
        
        - Removes LLM artifacts (extra tokens, repeated lines)
        - Ensures minimum substance (not one-word answers)
        - Keeps first sentence if extremely long
        - Maintains natural conversation flow
        
        Args:
            response_text: Raw LLM response
            
        Returns:
            Enhanced response string
        """
        # Clean up common LLM artifacts
        response_text = response_text.strip()
        
        # Remove trailing common LLM patterns
        response_text = response_text.rstrip("...")
        response_text = response_text.rstrip(",")
        
        # If response is very short (single word/short phrase), it's probably too minimal
        # This is a fallback (shouldn't happen with good prompts, but just in case)
        if len(response_text.split()) < 3 and not response_text.endswith(("?", "!")):
            self.logger.debug(f"[_enhance_response] Response too short, accepting as-is: '{response_text}'")
        
        return response_text