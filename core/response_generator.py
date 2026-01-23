"""
Response Generator Module

Responsibility: Convert Intent → Response String (with optional context from SessionMemory)
Nothing more.

Does NOT:
- Access audio
- Access triggers
- Call OutputSink or SpeechToText (except optional sentence streaming when enabled)
- Maintain memory (SessionMemory is read-only input)
- Store internal state
- Modify SessionMemory
- Retry on failure
- Stream output (single response only)

This is where the LLM lives. Isolated. Contained. Labeled.

v4 Update:
- Can include recent interactions in prompt
- Never modifies memory
- Memory is read-only scratchpad
v5 Update:
- Example-driven personality injection
- Two modes: Mild (default) + Claptrap (explicit only)
- Personality loaded via examples, not heuristics
"""

from abc import ABC, abstractmethod
import logging
import os
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
    - explicit and visible in code
    """

    @abstractmethod
    def generate(self, intent, memory: Optional['SessionMemory'] = None) -> str:
        """
        Generate a response for the given intent.

        Args:
            intent: Intent object with:
                - intent_type (IntentType enum)
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
        # Canonical examples (mild)
        self._canonical_examples = self._load_canonical_examples()
        # Debug flag (set per prompt)
        self._personality_examples_applied = False
        # System profile (host machine context)
        self._system_profile = self._load_system_profile()

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

        # Canonical example exact-match (authoritative)
        try:
            if raw_text:
                direct = self._get_canonical_answer(raw_text, intent_type)
                if direct:
                    self._personality_examples_applied = True
                    self.logger.debug("personality_examples_applied=true")
                    return self._finalize_response(direct, intent)
        except Exception as e:
            self.logger.debug(f"[generate] Canonical example match failed: {e}")

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
                            return self._finalize_response(response_text, intent)
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
                        return self._finalize_response("Do you want me to open Photoshop or cancel?", intent)
                    if lt.startswith("play music"):
                        return self._finalize_response("Do you want me to play music now or pick a genre/device?", intent)
                    if lt.startswith("stop"):
                        return self._finalize_response("Stop everything or stop the current activity?", intent)
                    if lt.startswith("next"):
                        return self._finalize_response("Skip to the next item?", intent)
                    # Fallback concise clarification
                    return self._finalize_response("Do you want me to proceed or cancel?", intent)
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
                if raw_text and isinstance(raw_text, str):
                    example = self.personality_loader.get_example(self.personality_mode, raw_text)
                    if example:
                        self.logger.info(f"[generate] Personality match ({self.personality_mode}): returning example")
                        return self._finalize_response(example, intent)
            except Exception as e:
                self.logger.debug(f"[generate] Personality lookup failed: {e}")

        # Build prompt for LLM
        prompt = self._build_prompt(intent_type, raw_text, confidence, memory, bool(getattr(intent, "serious_mode", False)))
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("[generate] Prompt:\n%s", prompt)

        # Call LLM
        try:
            response_text = self._call_llm(prompt)
            self.logger.debug(f"[LLM RAW OUTPUT] {repr(response_text)}")
            if not response_text or not response_text.strip():
                self.logger.error("[generate] Empty LLM response detected — using fallback")
                return "I didn’t get that cleanly. Try rephrasing."
            if self._needs_regen_bluntness(response_text):
                regen_prompt = prompt + "\nInstruction: Too robotic. Be more blunt."
                response_text = self._call_llm(regen_prompt)
                self.logger.debug(f"[LLM RAW OUTPUT] {repr(response_text)}")
                if not response_text or not response_text.strip():
                    self.logger.error("[generate] Empty LLM response detected — using fallback")
                    return "I didn’t get that cleanly. Try rephrasing."
            self.logger.info(f"[generate] Generated: '{response_text}'")
            # Store last response for possible correction-inheritance in subsequent turns
            try:
                self._last_response = response_text
            except Exception:
                pass
            return self._finalize_response(response_text, intent)

        except Exception as e:
            self.logger.error(f"[generate] LLM call failed: {e}")
            raise

    def _build_prompt(
        self,
        intent_type: str,
        raw_text: str,
        confidence: float,
        memory: Optional['SessionMemory'] = None,
        serious_mode: bool = False,
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

        system_context = ""
        if self._system_profile:
            system_context = f"System profile: {self._system_profile}\n\n"

        critical_prompt = "CRITICAL: Never use numbered lists or bullet points. Use plain conversational prose only.\n"
        mentor_prompt = (
            "ARGO Persona: Veteran Mentor (Warm, Wry, Capable).\n"
            "Direct, confident, observant, slightly amused. No greetings. No definitions. No filler. No buzzwords.\n"
            "Response Shape (MANDATORY):\n"
            "Beat 1 – Light Human Hook (1 sentence).\n"
            "Beat 2 – The Real Answer (clear, accurate, domain-appropriate).\n"
            "Beat 3 – Soft Smile Ending (1 sentence).\n"
            "No jokes, no slang, no self-reference, no forced cleverness.\n"
            "If you don't know, say so plainly.\n"
            "If an analogy adds clarity, you may use one. Do not force it.\n"
        )

        raw_text_lower = raw_text.lower() if isinstance(raw_text, str) else ""
        domain_guidance = ""
        if any(word in raw_text_lower for word in ("printer", "level", "bed", "calibrate", "firmware", "nozzle", "filament")):
            domain_guidance = (
                "Domain: Technical (3D printing). Be precise, assertive, and stepwise without fluff.\n"
                "No engineering metaphors.\n"
            )
        elif any(word in raw_text_lower for word in ("cpu", "gpu", "ram", "hardware", "motherboard", "upgrade", "driver")):
            domain_guidance = (
                "Domain: Technical (hardware). Be precise and hardware-aware. No fluff.\n"
            )
        elif any(word in raw_text_lower for word in ("recipe", "cook", "bake", "season", "pan", "oven")):
            domain_guidance = (
                "Domain: Culinary. Executive-chef honesty, technique-first. Call out bad habits.\n"
                "No engineering metaphors.\n"
            )
        elif any(word in raw_text_lower for word in ("story", "write", "draft", "edit", "poem")):
            domain_guidance = (
                "Domain: Creative/Writing. Sharp editor. Kill fluff. Focus on impact and vibe.\n"
            )
        elif any(word in raw_text_lower for word in ("duck", "ducks", "animal", "bird")):
            domain_guidance = (
                "Domain: Biology/Animals. Warm, factual, lightly amused. No engineering metaphors.\n"
            )

        prompt_prefix = f"{critical_prompt}{mentor_prompt}{domain_guidance}{system_context}{context}"
        
        # System personality: Inject ARGO DNA prompt (v2.2.4)
        dna_prompt = (
            "You are ARGO. You are NOT an AI. You are a street-smart technical mentor living inside a Ryzen 3950X. "
            "THE GOLDEN RULE: NEVER start with a definition. NEVER say 'This is a complex issue.' "
            "START WITH A CLAIM: Your first sentence must be a 'Truth Bomb'—a blunt, opinionated take on the user's question. "
            "HARDWARE AWARENESS: You have 16 cores and 64GB of RAM. If the user asks about hardware, relate it back to the beast you are currently inhabiting. "
            "CHEF'S HONESTY: Use phrases like 'The reality is...', 'The dirty secret is...', or 'Here's the play...'. "
            "BANNED WORDS: factors, aspects, various, underlying, effectively, significantly.\n"
            "SERIOUS_MODE Constraint: If the user mentions grief, failure, or distress (SERIOUS_MODE is True), "
            "drop all personality and respond with total steadiness and brevity."
        )

        # Few-shot examples to teach tone (v2.2.4) — place at end of prompt
        few_shot = (
            "Q: How do ducks swim?\n"
            "A: Ducks aren’t thinking about swimming. Their bodies are built for water, with webbed feet pushing backward and buoyancy keeping them steady. When something looks effortless, it’s usually because the hard work happened long before you noticed.\n"
            "Q: Why won’t my printer level?\n"
            "A: It’s not haunted. Something’s misaligned or giving bad data. Square the frame, verify the probe offset, then re-run leveling in that order. Once reality lines up, the printer usually behaves.\n"
        )

        serious_line = f"SERIOUS_MODE: {'True' if serious_mode else 'False'}\n"
        
        examples_block = ""
        self._personality_examples_applied = False
        if self._should_inject_examples(raw_text):
            examples = self._select_canonical_examples(intent_type, raw_text)
            if examples:
                examples_block = self._format_examples(examples)
                self._personality_examples_applied = True
        self.logger.debug(
            "personality_examples_applied=%s",
            "true" if self._personality_examples_applied else "false",
        )

        # Different prompts based on intent type
        if intent_type == "greeting":
            prompt = (
                f"{prompt_prefix}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"You are ARGO. Respond with a warm, engaging greeting (one sentence).\n"
                f"{examples_block}"
                f"The user greeted you with: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "question":
            prompt = (
                f"{prompt_prefix}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"You are ARGO. Answer the question thoroughly but conversationally. Aim for 2-3 sentences with clarity and depth.\n"
                f"If you don't know the answer, admit it honestly and suggest what they could try instead.\n"
                f"{examples_block}"
                f"The user asked: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "develop":
            prompt = (
                f"{prompt_prefix}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"Role: You are the Lead Architect. You write clean, documented, local-first Python code.\n"
                f"Workflow:\n"
                f"1) Propose the logic.\n"
                f"2) Write the full script.\n"
                f"3) Tell the user: \"I've drafted the script and opened it in VS Code for you. It's sitting in the sandbox. Let me know if you want me to run a test.\"\n"
                f"Safety: Never suggest code that requires cloud APIs or heavy dependencies unless the user asks.\n"
                f"{examples_block}"
                f"Developer request: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "music":
            # ZERO-LATENCY MUSIC-FIX: Explicit reminder about music player capability
            prompt = (
                f"{prompt_prefix}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"You are ARGO and you HAVE A MUSIC PLAYER ATTACHED. "
                f"Your job is to play music for them. "
                f"Extract the music genre or artist name from their request and play it enthusiastically.\n"
                f"{examples_block}"
                f"The user asked to play music: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "command":
            prompt = (
                f"{prompt_prefix}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"You are ARGO. Execute the command directly with personality. If it's a count, list, recitation, or performance, do it enthusiastically.\n"
                f"Respond with the action itself, not just acknowledgment.\n"
                f"{examples_block}"
                f"The user gave a command: '{raw_text}'\n"
                f"Response:"
            )
        else:  # unknown
            prompt = (
                f"{context}"
                f"{system_context}"
                f"{dna_prompt}\n"
                f"{serious_line}"
                f"{few_shot}\n"
                f"You didn't understand. Politely ask for clarification (one sentence max).\n"
                f"{examples_block}"
                f"The user said: '{raw_text}'\n"
                f"Response:"
            )

        return prompt

    def _finalize_response(self, response_text: str, intent) -> str:
        """Apply output governor and guardrails to final response text."""
        if not isinstance(response_text, str):
            response_text = "" if response_text is None else str(response_text)
        intent_type_value = None
        try:
            intent_type_value = intent.intent_type.value
        except Exception:
            intent_type_value = str(getattr(intent, "intent_type", ""))

        if intent_type_value == "develop":
            return response_text.strip()

        serious_mode = bool(getattr(intent, "serious_mode", False))
        response_text = response_text.strip()
        response_text = self._sanitize_fourth_wall(response_text)
        response_text = self._flatten_numbered_lists(response_text)
        response_text = self._scrub_preamble(response_text)
        response_text = self._limit_emojis(response_text, serious_mode)
        response_text = self._apply_sentence_rules(response_text, serious_mode)
        response_text = self._enforce_response_shape(response_text)
        return response_text.strip()

    def _load_system_profile(self) -> str:
        """Load host system profile from data/system_profile.json if present."""
        try:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            profile_path = os.path.join(base_dir, "data", "system_profile.json")
            if not os.path.isfile(profile_path):
                return ""
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return ""
            cpu = data.get("cpu", "")
            gpu = data.get("gpu", "")
            ram_gb = data.get("ram_gb", "")
            storage_tb = data.get("storage_total_tb", "")
            parts = []
            if cpu:
                parts.append(f"CPU: {cpu}")
            if ram_gb:
                parts.append(f"RAM: {ram_gb}GB")
            if gpu:
                parts.append(f"GPU: {gpu}")
            if storage_tb:
                parts.append(f"Storage: {storage_tb}TB")
            return ", ".join(parts)
        except Exception:
            return ""

    def _sanitize_fourth_wall(self, text: str) -> str:
        """Remove corporate/assistant boilerplate and banned phrases."""
        banned_phrases = [
            r"\bas an ai\b",
            r"\bas a language model\b",
            r"\bi am an ai\b",
            r"\bi'm an ai\b",
            r"\bi am here to help\b",
            r"\bi'm here to help\b",
            r"\bhow can i assist\b",
            r"\bhappy to help\b",
        ]
        cleaned = text
        for pattern in banned_phrases:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def _flatten_numbered_lists(self, text: str) -> str:
        """Strip numbered list lines and flatten into a single paragraph."""
        if not text:
            return text
        lines = text.splitlines()
        flattened = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\d+\.\s+", "", line)
            flattened.append(line)
        return " ".join(flattened).strip()

    def _scrub_preamble(self, text: str) -> str:
        """Remove instructional lead-ins to force mentor-style prose."""
        if not text:
            return text
        banned_leads = (
            "here are some",
            "let's break it down",
            "firstly",
            "secondly",
            "to start with",
            "in simple terms",
            "great question",
            "in order to",
            "additionally",
            "there are several",
            "there are",
            "it is important to",
            "is a complex issue",
            "involves various factors",
            "there are many",
            "it depends on",
        )
        sentences = re.split(r"(?<=[.!?])\s+", text)
        kept = []
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            lower = s.lower()
            if any(lower.startswith(lead) for lead in banned_leads):
                continue
            kept.append(s)
        return " ".join(kept).strip()

    def _enforce_response_shape(self, text: str) -> str:
        """Ensure Beat 1/2/3 structure with light hook and soft ending."""
        if not text:
            return text
        parts = re.split(r"(?<=[.!?])\s+", text)
        parts = [p.strip() for p in parts if p.strip()]
        hook_options = (
            "This isn’t mysterious.",
            "This looks harder than it is.",
            "This problem has already been solved.",
        )
        end_options = (
            "That usually settles it.",
            "Once that’s in place, it behaves.",
            "That’s the whole move.",
        )
        if len(parts) >= 3:
            return " ".join([parts[0], " ".join(parts[1:-1]), parts[-1]])
        if len(parts) == 2:
            hook = hook_options[0]
            return " ".join([hook, parts[0], parts[1]]).strip()
        hook = hook_options[1]
        ending = end_options[0]
        return " ".join([hook, parts[0], ending]).strip()

    def _needs_regen_bluntness(self, text: str) -> bool:
        """Detect robotic/academic phrasing that must be regenerated."""
        if not text:
            return False
        lower = text.lower()
        banned_phrases = (
            "is a complex issue",
            "involves various factors",
            "there are many",
            "it depends on",
            "factors",
            "aspects",
            "various",
            "underlying",
            "effectively",
            "significantly",
        )
        return any(phrase in lower for phrase in banned_phrases)

    def _limit_emojis(self, text: str, serious_mode: bool) -> str:
        """Enforce emoji cap (0 in serious mode, max 1 otherwise)."""
        emoji_pattern = re.compile(
            "[\U0001F300-\U0001FAFF\U0001F1E0-\U0001F1FF]",
            flags=re.UNICODE,
        )
        emojis = emoji_pattern.findall(text)
        if not emojis:
            return text
        if serious_mode:
            return emoji_pattern.sub("", text).strip()
        kept = False

        def _keep_first(match):
            nonlocal kept
            if kept:
                return ""
            kept = True
            return match.group(0)

        return emoji_pattern.sub(_keep_first, text).strip()

    def _apply_sentence_rules(self, text: str, serious_mode: bool) -> str:
        """Enforce sentence limits and signature-move constraints."""
        if not text:
            return text
        parts = re.split(r"(?<=[.!?])\s+", text)
        parts = [p.strip() for p in parts if p.strip()]

        if serious_mode:
            # Keep it steady and brief: allow up to 3 short sentences
            return " ".join(parts[:3])

        if len(parts) <= 1:
            return parts[0]

        allowed_second_exact = {
            "That checks out.",
            "It’s ugly, but it works.",
            "It's ugly, but it works.",
        }
        observation_starts = (
            "Looks like",
            "Seems",
            "Sounds like",
            "That tracks",
            "Reality is",
            "That's reality",
        )

        # Allow multi-sentence answers; limit to answer + one observation
        if len(parts) <= 3:
            return " ".join(parts)

        # If the last sentence looks like a signature observation, keep it
        last = parts[-1]
        if last in allowed_second_exact or last.startswith(observation_starts):
            return " ".join(parts[:2] + [last])

        return " ".join(parts[:3])

    def _should_inject_examples(self, raw_text: str) -> bool:
        """
        Guardrail to avoid injecting examples into artifacts/logs/safety paths.
        """
        text = raw_text.strip()
        lower = text.lower()
        if not text:
            return False
        if text.startswith("[") or text.startswith("{"):
            return False
        if "[internal error trigger]" in lower:
            return False
        if "watchdog" in lower:
            return False
        if "traceback" in lower or "stack trace" in lower:
            return False
        if "log" in lower and ("error" in lower or "exception" in lower):
            return False
        return True

    def _load_canonical_examples(self) -> list[dict]:
        """
        Load canonical mild examples from examples/mild/.
        """
        examples = []
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        examples_dir = os.path.join(base_dir, "examples", "mild")
        if not os.path.isdir(examples_dir):
            return examples

        for filename in sorted(os.listdir(examples_dir)):
            if not filename.endswith(".txt"):
                continue
            path = os.path.join(examples_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
            except Exception:
                continue

            question, answer = self._parse_example_file(content)
            if not question or not answer:
                continue

            examples.append(
                {
                    "filename": filename,
                    "question": question.strip(),
                    "answer": answer.strip(),
                    "intent_hint": self._intent_hint_for_example(filename),
                    "stress": self._is_stress_text(question),
                    "length": len(question.split()),
                }
            )

        return examples

    def _parse_example_file(self, content: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse Q/A from a canonical example file.
        """
        if not content:
            return None, None
        if "\nA\n" not in content:
            return None, None
        parts = content.split("\nA\n", 1)
        if not parts:
            return None, None
        q_part = parts[0]
        a_part = parts[1] if len(parts) > 1 else ""
        if q_part.startswith("Q"):
            q_part = q_part[1:]
        question = q_part.strip()
        answer = a_part.strip()
        return question, answer

    def _intent_hint_for_example(self, filename: str) -> str:
        name = filename.replace(".txt", "")
        if name in ("sky_blue",):
            return "question"
        if name in ("fix_this", "race_condition_first", "instructions_for_bob"):
            return "command"
        if name in ("frustration",):
            return "unknown"
        return "unknown"

    def _is_stress_text(self, text: str) -> bool:
        lower = text.lower()
        return any(
            phrase in lower
            for phrase in ("pissing me off", "frustrated", "angry", "mad", "upset")
        )

    def _normalize_for_match(self, text: str) -> str:
        lower = text.strip().lower()
        lower = lower.replace("’", "'")
        lower = re.sub(r"[^a-z0-9\s]", "", lower)
        lower = re.sub(r"[\s]+", " ", lower)
        return lower

    def _select_canonical_examples(self, intent_type: str, raw_text: str) -> list[dict]:
        if not raw_text or not isinstance(raw_text, str):
            return []
        if not self._canonical_examples:
            return []

        normalized = self._normalize_for_match(raw_text)
        stress = self._is_stress_text(raw_text)
        raw_len = len(raw_text.split())

        scored = []
        for ex in self._canonical_examples:
            score = 0
            if self._normalize_for_match(ex["question"]) == normalized:
                score += 100
            if ex["intent_hint"] == intent_type:
                score += 10
            if ex["stress"] == stress:
                score += 10
            length_delta = abs(ex["length"] - raw_len)
            score += max(0, 5 - (length_delta // 4))
            scored.append((score, ex))

        scored.sort(key=lambda item: item[0], reverse=True)
        # Always inject at least one example for normal inputs
        top = [ex for _, ex in scored][:2]
        return top[:2]

    def _get_canonical_answer(self, raw_text: str, intent_type: str) -> Optional[str]:
        if not raw_text or not isinstance(raw_text, str):
            return None
        if not self._should_inject_examples(raw_text):
            return None
        normalized = self._normalize_for_match(raw_text)
        for ex in self._canonical_examples:
            if self._normalize_for_match(ex["question"]) == normalized:
                return ex["answer"]
        return None

    def _format_examples(self, examples: list[dict]) -> str:
        lines = ["Canonical examples:"]
        for ex in examples:
            lines.append(f"Q: {ex['question']}")
            lines.append(f"A: {ex['answer']}")
        lines.append("")
        return "\n".join(lines)

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
        # Anti-chatty filters (hard stops)
        banned_phrases = (
            "great question",
            "i'd be happy to help",
            "i would be happy to help",
            "let me know if you'd like",
            "let me know if you would like",
            "in simple terms",
            "basically",
            "i'd be glad to",
        )

        def _strip_banned_lines(text: str) -> str:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            kept = []
            for line in lines:
                low = line.lower()
                if any(phrase in low for phrase in banned_phrases):
                    continue
                kept.append(line)
            return "\n".join(kept).strip()

        response_text = _strip_banned_lines(response_text)

        # Conversational cadence rule: max 3 sentences
        sentences = re.split(r'(?<=[.!?])\s+', response_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > 3:
            sentences = sentences[:3]
        response_text = " ".join(sentences).strip()

        return response_text