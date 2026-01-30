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

# ============================================================================
# 1) IMPORTS
# ============================================================================
from abc import ABC, abstractmethod
import logging
import time
import os
import re
import json
from typing import Optional
from core.config import ENABLE_LLM_TTS_STREAMING, get_config, get_runtime_overrides
from core.startup_checks import check_ollama
from core.policy import LLM_TIMEOUT_SECONDS, LLM_WATCHDOG_SECONDS, WATCHDOG_FALLBACK_RESPONSE
from core.watchdog import Watchdog
from core.output_sink import get_output_sink
from core.intent_parser import IntentType
from system_health import get_temperature_health, get_disk_info, get_system_full_report
from system_profile import get_system_profile, get_gpu_profile
from core.instrumentation import log_event

# ============================================================================
# 1) PERSONALITY SUPPORT CONSTANTS
# ============================================================================
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
        try:
            config = get_config()
            self.model = config.get("llm.model", "qwen:latest")
        except Exception:
            self.model = "qwen:latest"
        
        # Hardcoded generation parameters
        self.temperature = 0.85  # Increased for more personality and creativity (0.7 was too dry)
        self.max_tokens = 2000  # Plenty of room for full answers (2-3 min speech worth)
        
        # ====================================================================
        # 2) PERSONALITY INJECTION (EXAMPLE-DRIVEN)
        # ====================================================================
        # Personality injection (example-driven)
        from core.personality import get_personality_loader
        self.personality_loader = get_personality_loader()
        self._config = get_config()
        self.personality_mode = self._resolve_personality_mode()
        
        self.logger = logger
        self.logger.info("[LLMResponseGenerator v5] Initialized")
        self.logger.debug(f"  Endpoint: {self.ollama_url}")
        self.logger.debug(f"  Model: {self.model}")
        self.logger.debug(f"  Temperature: {self.temperature}")
        self.logger.debug(f"  Max tokens: {self.max_tokens}")
        self.logger.debug(f"  Personality mode: {self.personality_mode}")
        self.enabled = check_ollama()
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
        # ====================================================================
        # 3) PERSONALITY EXAMPLES + CANONICAL VOICE
        # ====================================================================
        # Canonical voice examples (authoritative)
        self._canonical_voice_text = self._load_canonical_voice_text()
        self._canonical_examples = self._load_canonical_examples()
        # Debug flag (set per prompt)
        self._personality_examples_applied = False
        # System profile (host machine context)
        self._system_profile = self._load_system_profile()
        # LLM timing markers
        self._llm_request_start = None
        self._llm_first_token_logged = False

    # ====================================================================
    # 4) PERSONALITY MODE RESOLUTION
    # ====================================================================
    def _resolve_personality_mode(self) -> str:
        try:
            overrides = get_runtime_overrides()
            mode = overrides.get("personality_mode") or self._config.get("personality.mode", "mild")
        except Exception:
            mode = "mild"
        if mode not in self.personality_loader.SUPPORTED_MODES:
            mode = self.personality_loader.DEFAULT_MODE
        return mode

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

        raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
        for keyword in ("stop", "goodbye", "quit", "exit"):
            if keyword in raw_text_lower:
                return "Goodbye." if keyword in {"goodbye", "quit", "exit"} else "Stopping."

        if intent.intent_type in {IntentType.SYSTEM_HEALTH, IntentType.SYSTEM_INFO}:
            subintent = getattr(intent, "subintent", None)
            raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
            if subintent == "full":
                report = get_system_full_report()
                return self._format_system_full_report(report)
            if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
                disks = get_disk_info()
                if not disks:
                    return "Hardware information unavailable."
                drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
                if not drive_match:
                    drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
                if drive_match:
                    letter = drive_match.group(1).upper()
                    key = f"{letter}:"
                    info = disks.get(key) or disks.get(letter)
                    if info:
                        return (
                            f"{letter} drive is {info['percent']} percent full, "
                            f"with {info['free_gb']} gigabytes free."
                        )
                    return "Hardware information unavailable."
                if "fullest" in raw_text_lower or "most used" in raw_text_lower:
                    disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                    return f"{disk} is the fullest drive at {info['percent']} percent used."
                if "most free" in raw_text_lower or "most space" in raw_text_lower:
                    disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                    return f"{disk} has the most free space at {info['free_gb']} gigabytes free."
                total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
                return f"You have {total_free} gigabytes free across {len(disks)} drives."
            if subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
                profile = get_system_profile()
                gpus = get_gpu_profile()
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
                        return f"Your system has {ram_gb} gigabytes of memory{extra_text}."
                    return (
                        f"Your system has {ram_gb} gigabytes of memory."
                        if ram_gb is not None
                        else "Hardware information unavailable."
                    )
                if subintent == "cpu":
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
                        return f"Your CPU is a {cpu_name}{detail}." if cpu_name else "Hardware information unavailable."
                    return (
                        f"Your CPU is a {cpu_name}."
                        if cpu_name
                        else "Hardware information unavailable."
                    )
                if subintent == "gpu":
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
                            return "Your GPU(s): " + "; ".join(gpu_bits) + "."
                        return f"Your GPU is {gpus[0].get('name')}."
                    return "No GPU detected."
                if subintent == "os":
                    os_name = profile.get("os") if profile else None
                    return (
                        f"You are running {os_name}."
                        if os_name
                        else "Hardware information unavailable."
                    )
                if subintent == "motherboard":
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
                        return f"Your motherboard is {board}{extra}." if board else "Hardware information unavailable."
                    return (
                        f"Your motherboard is {board}."
                        if board
                        else "Hardware information unavailable."
                    )
                cpu_name = profile.get("cpu") if profile else None
                ram_gb = profile.get("ram_gb") if profile else None
                gpu_name = gpus[0].get("name") if gpus else None
                if not cpu_name or ram_gb is None:
                    return "Hardware information unavailable."
                summary = f"Your CPU is a {cpu_name}. You have {ram_gb} gigabytes of memory."
                if gpu_name:
                    summary += f" Your GPU is {gpu_name}."
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
                        summary += " Storage: " + "; ".join(drive_bits) + "."
                return summary

        if intent.intent_type == IntentType.SYSTEM_HEALTH and getattr(intent, "subintent", None) == "temperature":
            temps = get_temperature_health()
            if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                return "Temperature sensors are not available on this system."
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

        if not self.enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""

        # Extract intent information
        intent_type = intent.intent_type.value  # "greeting", "question", etc.
        raw_text = intent.raw_text  # Original user input
        confidence = intent.confidence
        serious_mode = bool(getattr(intent, "serious_mode", False))

        # ====================================================================
        # 5) PER-REQUEST PERSONALITY MODE REFRESH
        # ====================================================================
        # Refresh personality mode per request (runtime overrides can change)
        self.personality_mode = self._resolve_personality_mode()

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
                            try:
                                response_text = self._call_llm(prompt)
                            except Exception as llm_error:
                                self.logger.error(f"[generate] LLM call failed in correction inheritance: {llm_error}")
                                log_event("LLM_UNAVAILABLE")
                                raise  # Re-raise to outer handler which will skip correction inheritance
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
        if intent_type != "command" and not serious_mode:
            try:
                if raw_text and isinstance(raw_text, str):
                    example = self.personality_loader.get_example(self.personality_mode, raw_text)
                    if example:
                        self.logger.info(f"[generate] Personality match ({self.personality_mode}): returning example")
                        return self._finalize_response(example, intent)
            except Exception as e:
                self.logger.debug(f"[generate] Personality lookup failed: {e}")

        # Build prompt for LLM
        prompt = self._build_prompt(intent_type, raw_text, confidence, memory, serious_mode)
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("[generate] Prompt:\n%s", prompt)

        # Call LLM
        try:
            response_text = self._call_llm(prompt)
            self.logger.debug(f"[LLM RAW OUTPUT] {repr(response_text)}")
            if not response_text or not response_text.strip():
                self.logger.error("[generate] Empty LLM response detected — using fallback")
                return "I didn’t get that cleanly. Try rephrasing."
            if self._streamed_output:
                return self._finalize_response(response_text, intent)
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
            log_event("LLM_UNAVAILABLE")
            # Return fallback response without raising
            return (
                "My internal brain is offline right now, "
                "but I'm still listening. Give me a second to reconnect."
            )
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
        persona_contract = (
            "You are ARGO, a veteran mentor.\n"
            "You speak clearly, confidently, and with quiet humor.\n"
            "Start with a direct observation or conclusion.\n"
            "Explain only what matters.\n"
            "End with a line that adds perspective or a small smile.\n"
            "Do not perform, hype, or explain yourself.\n"
        )

        if serious_mode:
            persona_contract = (
                "You are ARGO in SERIOUS_MODE.\n"
                "Tone: clean, calm, surgical. No jokes. No sarcasm.\n"
                "Give a direct answer, then a brief explanation.\n"
                "No fluff. No theatrics. No filler.\n"
            )
        elif self.personality_mode == "tommy_gunn":
            persona_contract = (
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

        canonical_block = ""
        if self._canonical_voice_text:
            canonical_block = f"{self._canonical_voice_text.strip()}\n\n"

        # Voice priority:
        # Canonical examples > Persona contract > Task instructions > User query
        # If tone drifts, adjust examples, not rules.
        prompt_prefix = f"{canonical_block}{persona_contract}{critical_prompt}{domain_guidance}{system_context}{context}"

        serious_line = f"SERIOUS_MODE: {'True' if serious_mode else 'False'}\n"
        
        self._personality_examples_applied = bool(canonical_block)
        self.logger.debug(
            "personality_examples_applied=%s",
            "true" if self._personality_examples_applied else "false",
        )

        # Different prompts based on intent type
        if intent_type == "greeting":
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"Respond with a warm, engaging greeting (one sentence).\n"
                f"The user greeted you with: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "question":
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"Answer the question thoroughly but conversationally. Aim for 2-3 sentences with clarity and depth.\n"
                f"If you don't know the answer, admit it honestly and suggest what they could try instead.\n"
                f"The user asked: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "develop":
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"Role: You are the Lead Architect. You write clean, documented, local-first Python code.\n"
                f"Workflow:\n"
                f"1) Propose the logic.\n"
                f"2) Write the full script.\n"
                f"3) Tell the user: \"I've drafted the script and opened it in VS Code for you. It's sitting in the sandbox. Let me know if you want me to run a test.\"\n"
                f"Safety: Never suggest code that requires cloud APIs or heavy dependencies unless the user asks.\n"
                f"Developer request: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "music":
            # ZERO-LATENCY MUSIC-FIX: Explicit reminder about music player capability
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"You are ARGO and you HAVE A MUSIC PLAYER ATTACHED. "
                f"Your job is to play music for them. "
                f"Extract the music genre or artist name from their request and play it enthusiastically.\n"
                f"The user asked to play music: '{raw_text}'\n"
                f"Response:"
            )
        elif intent_type == "command":
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"You are ARGO. Execute the command directly with personality. If it's a count, list, recitation, or performance, do it enthusiastically.\n"
                f"Respond with the action itself, not just acknowledgment.\n"
                f"The user gave a command: '{raw_text}'\n"
                f"Response:"
            )
        else:  # unknown
            prompt = (
                f"{prompt_prefix}"
                f"{serious_line}"
                f"You didn't understand. Politely ask for clarification (one sentence max).\n"
                f"The user said: '{raw_text}'\n"
                f"Response:"
            )

        return prompt

    def _finalize_response(self, response_text: str, intent) -> str:
        """Apply output governor and guardrails to final response text."""
        if not isinstance(response_text, str):
            response_text = "" if response_text is None else str(response_text)
        if bool(getattr(self, "_streamed_output", False)):
            return response_text.strip()
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
        response_text = self._strip_prompt_artifacts(response_text)
        response_text = self._scrub_system_output(response_text)
        response_text = self._flatten_numbered_lists(response_text)
        response_text = self._scrub_preamble(response_text)
        response_text = self._limit_emojis(response_text, serious_mode)
        response_text = self._apply_sentence_rules(response_text, serious_mode)
        response_text = self._enforce_response_shape(response_text)
        return response_text.strip()

    def _strip_prompt_artifacts(self, text: str) -> str:
        """Remove prompt leakage and section labels from responses."""
        if not text:
            return text
        # Remove leaked system flags
        text = re.sub(r"\bSERIOUS_MODE\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCRITICAL\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        # Remove section labels
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

    def _scrub_system_output(self, text: str) -> str:
        """Remove any system diagnostics from user-facing responses."""
        if not text:
            return text
        patterns = [
            r"\bVAD\b",
            r"\bSTT\b",
            r"\bLLM\b",
            r"\bTTS\b",
            r"\bAUDIO\b",
            r"\bTHREAD\b",
            r"\bDEBUG\b",
            r"\binteraction_id\b",
            r"\brms\b",
            r"\bpeak\b",
            r"\bsilence\b",
            r"\bthreshold\b",
        ]
        cleaned = text
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

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
        if len(parts) >= 3:
            return " ".join([parts[0], " ".join(parts[1:-1]), parts[-1]])
        return " ".join(parts).strip()

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

    def _load_canonical_voice_text(self) -> str:
        """
        Load the canonical voice examples text (authoritative prompt anchor).
        """
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(base_dir, "personality", "canonical_voice_examples.txt")
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _load_canonical_examples(self) -> list[dict]:
        """
        Load canonical voice examples from personality/canonical_voice_examples.txt.
        """
        examples = []
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(base_dir, "personality", "canonical_voice_examples.txt")
        if not os.path.isfile(path):
            return examples

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception:
            return examples

        pairs = self._parse_canonical_voice_examples(content)
        for idx, (question, answer) in enumerate(pairs):
            if not question or not answer:
                continue
            examples.append(
                {
                    "filename": f"canonical_voice_examples.txt#{idx + 1}",
                    "question": question.strip(),
                    "answer": answer.strip(),
                    "intent_hint": "question",
                    "stress": self._is_stress_text(question),
                    "length": len(question.split()),
                }
            )

        return examples

    def _parse_canonical_voice_examples(self, content: str) -> list[tuple[str, str]]:
        """
        Parse multiple Q/A pairs from canonical voice examples text.
        Expected format: "Q: ..." then "A: ..." (answers may span multiple lines).
        """
        if not content:
            return []
        lines = [line.rstrip() for line in content.splitlines()]
        pairs: list[tuple[str, str]] = []
        current_q = None
        current_a_lines: list[str] = []

        def _commit():
            nonlocal current_q, current_a_lines
            if current_q and current_a_lines:
                pairs.append((current_q.strip(), " ".join(s.strip() for s in current_a_lines if s.strip()).strip()))
            current_q = None
            current_a_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Q:"):
                _commit()
                current_q = stripped[2:].strip()
                continue
            if stripped.startswith("A:"):
                current_a_lines = [stripped[2:].strip()]
                continue
            if current_a_lines:
                current_a_lines.append(stripped)

        _commit()
        return pairs

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
            self._llm_request_start = time.monotonic()
            self._llm_first_token_logged = False
            log_event("LLM_REQUEST_START", stage="llm")
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
                    log_event("LLM_WATCHDOG", stage="llm")
                    return WATCHDOG_FALLBACK_RESPONSE

                if not response_text:
                    raise RuntimeError("LLM returned empty response")

                if self._llm_request_start:
                    total_ms = (time.monotonic() - self._llm_request_start) * 1000
                    log_event(f"LLM_DONE {total_ms:.0f}ms", stage="llm")

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
                log_event("LLM_WATCHDOG", stage="llm")
                return WATCHDOG_FALLBACK_RESPONSE

            if not response_text:
                raise RuntimeError("LLM returned empty response")

            # Enhance response quality
            response_text = self._enhance_response(response_text)

            if self._llm_request_start:
                total_ms = (time.monotonic() - self._llm_request_start) * 1000
                log_event(f"LLM_DONE {total_ms:.0f}ms", stage="llm")

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
        log_event("LLM_STREAM_START", stage="llm")

        sink = None
        try:
            sink = get_output_sink()
        except Exception:
            sink = None

        buffer = ""
        full_response_parts = []
        sentence_counter = 0
        first_sentence_seen = False
        pending_sentence = ""

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except Exception:
                continue

            chunk = data.get("response", "")
            if chunk:
                if not self._llm_first_token_logged and self._llm_request_start:
                    first_token_ms = (time.monotonic() - self._llm_request_start) * 1000
                    log_event(f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms", stage="llm")
                    self._llm_first_token_logged = True
                buffer += chunk
                full_response_parts.append(chunk)

                while True:
                    boundary_index = self._find_sentence_boundary(buffer)
                    if boundary_index == -1:
                        if len(buffer) >= 150:
                            sentence = buffer[:150]
                            buffer = buffer[150:]
                        else:
                            break
                    else:
                        sentence = buffer[:boundary_index]
                        buffer = buffer[boundary_index:]
                    buffer = buffer.lstrip()
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(sentence.split()) < 12:
                        pending_sentence = f"{pending_sentence} {sentence}".strip() if pending_sentence else sentence
                        continue
                    if pending_sentence:
                        sentence = f"{pending_sentence} {sentence}".strip()
                        pending_sentence = ""
                    filtered = self._apply_inline_governor(sentence, first_sentence=not first_sentence_seen)
                    if filtered is None:
                        continue
                    self._enqueue_sentence(sink, filtered)
                    sentence_counter += 1
                    if not first_sentence_seen:
                        self.logger.debug("[_stream_llm_and_enqueue] First sentence enqueued")
                        first_sentence_seen = True

            if data.get("done"):
                break

        # Flush remaining partial sentence
        remaining = buffer.strip()
        if pending_sentence:
            remaining = f"{pending_sentence} {remaining}".strip() if remaining else pending_sentence
        if remaining:
            filtered = self._apply_inline_governor(remaining, first_sentence=not first_sentence_seen)
            if filtered is not None:
                self._enqueue_sentence(sink, filtered)
                sentence_counter += 1

        self.logger.debug("[_stream_llm_and_enqueue] Streaming complete")
        log_event("LLM_STREAM_END", stage="llm")

        return "".join(full_response_parts).strip()

    def _find_sentence_boundary(self, text: str) -> int:
        """Return index after earliest sentence boundary (.?! + whitespace/end), or -1 if none."""
        if not text:
            return -1
        for idx, ch in enumerate(text):
            if ch in ".!?":
                next_ch = text[idx + 1] if idx + 1 < len(text) else ""
                if next_ch == "" or next_ch.isspace():
                    return idx + 1
        return -1

    def _apply_inline_governor(self, sentence: str, first_sentence: bool) -> Optional[str]:
        """
        Apply minimal inline governor (filtering only) per sentence.
        Drops banned lead-ins on the first sentence only.
        """
        if not sentence:
            return None
        if first_sentence:
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
            lower = sentence.lower().strip()
            if any(lower.startswith(lead) for lead in banned_leads):
                return None
        return sentence

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