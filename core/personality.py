"""
Personality Injection - Example-Driven System

Loads personality examples based on explicit mode.

Rules (from personality_injection_design_reference-clap.txt):
- Personality is ONLY example-driven
- Modes: Mild (default), Claptrap (explicit only), Tommy Gunn (explicit only)
- No rules, sliders, heuristics, or tone logic
- Examples stored as Q→A pairs in examples/{mode}/*.txt
- If no example found or loading fails → default to Mild
"""

import os
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# 1) PERSONALITY LOADER (PUBLIC API)
# ============================================================================
class PersonalityLoader:
    """Load personality examples from disk.

    Design:
    - Example-driven only (no heuristics, no sliders)
    - Explicit mode selection (mild/claptrap/tommy_gunn)
    - Cached to avoid repeated disk reads
    """
    
    SUPPORTED_MODES = ["mild", "claptrap", "tommy_gunn"]
    DEFAULT_MODE = "mild"
    
    def __init__(self, examples_dir: str = "examples"):
        """Initialize with examples directory."""
        # 1.1) Resolve examples directory
        # Convert relative path to absolute if needed
        if not os.path.isabs(examples_dir):
            # Get the directory of this file (core/)
            core_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(core_dir)
            examples_dir = os.path.join(parent_dir, examples_dir)
        
        # 1.2) Internal state
        self.examples_dir = examples_dir
        self.cache: Dict[str, List[Dict[str, str]]] = {}
        
    def load_examples(self, mode: str = DEFAULT_MODE) -> List[Dict[str, str]]:
        """
        Load Q→A examples for given mode.
        
        Args:
            mode: "mild" or "claptrap"
            
        Returns:
            List of {"question": str, "answer": str} dicts
        """
        # 2.1) Validate mode
        if mode not in self.SUPPORTED_MODES:
            logger.warning(f"[Personality] Unknown mode '{mode}', defaulting to {self.DEFAULT_MODE}")
            mode = self.DEFAULT_MODE
        
        # 2.2) Return cached if available
        if mode in self.cache:
            return self.cache[mode]
        
        # 2.3) Load from disk
        examples = []
        mode_dir = os.path.join(self.examples_dir, mode)
        
        if not os.path.exists(mode_dir):
            logger.warning(f"[Personality] Mode directory not found: {mode_dir}")
            return []
        
        # 2.4) Parse files (Q/A pairs)
        try:
            for filename in sorted(os.listdir(mode_dir)):
                if not filename.endswith(".txt"):
                    continue
                
                filepath = os.path.join(mode_dir, filename)
                pairs = self._parse_file(filepath)
                examples.extend(pairs)
                logger.debug(f"[Personality] Loaded {len(pairs)} examples from {filename}")
            
            self.cache[mode] = examples
            logger.info(f"[Personality] Loaded {len(examples)} total examples for mode '{mode}'")
            return examples
        
        except Exception as e:
            logger.error(f"[Personality] Failed to load examples for mode '{mode}': {e}")
            return []
    
    def _parse_file(self, filepath: str) -> List[Dict[str, str]]:
        """
        Parse Q→A file.
        
        Format:
            Q: Question text here
            A: Answer text here
            
            Q: Next question
            A: Next answer
        
        Args:
            filepath: Path to .txt file
            
        Returns:
            List of {"question": str, "answer": str} dicts
        """
        # 3.1) Parse loop state
        pairs = []
        current_q = None
        current_a = None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            i = 0
            # 3.2) Single-pass parse (preserves order)
            while i < len(lines):
                line = lines[i].strip()
                i += 1
                
                if not line:
                    continue
                
                if line.startswith("Q:"):
                    # If we have a previous pair, save it
                    if current_q is not None and current_a is not None:
                        pairs.append({"question": current_q, "answer": current_a})
                    
                    current_q = line[2:].strip()
                    current_a = None
                
                elif line.startswith("A:"):
                    current_a = line[2:].strip()
                    
                    # Multi-line answers: consume following indented lines
                    while i < len(lines):
                        next_line = lines[i]
                        if not next_line.strip():
                            i += 1
                            continue
                        if next_line.startswith(("Q:", "A:")):
                            break
                        if next_line[0] not in (" ", "\t"):
                            break
                        
                        current_a += "\n" + next_line.strip()
                        i += 1
            
            # 3.3) Save last pair
            if current_q is not None and current_a is not None:
                pairs.append({"question": current_q, "answer": current_a})
        
        except Exception as e:
            logger.error(f"[Personality] Failed to parse {filepath}: {e}")
        
        return pairs
    
    def get_example(self, mode: str, question: str) -> Optional[str]:
        """
        Find example answer for question (keyword-based match).
        
        Matches if:
        - Exact phrase match (case-insensitive)
        - Or all main keywords from user question appear in example question
        
        Args:
            mode: "mild" or "claptrap"
            question: User question
            
        Returns:
            Example answer if found, None otherwise
        """
        # 4.1) Load examples for mode
        examples = self.load_examples(mode)
        
        question_lower = question.lower()
        
        # 4.2) Extract keywords (filter out common stop words)
        stop_words = {"do", "why", "what", "how", "is", "the", "a", "an", "that", "this", "i", "my", "you", "your"}
        user_keywords = [w for w in question_lower.split() if w and w not in stop_words and len(w) > 2]
        
        for ex in examples:
            ex_q = ex["question"].lower()
            
            # 4.3) Exact substring match first
            if question_lower in ex_q or ex_q in question_lower:
                logger.debug(f"[Personality] Exact match found for '{question}'")
                return ex["answer"]
            
            # 4.4) Keyword match (all user keywords appear in example question)
            if user_keywords and all(kw in ex_q for kw in user_keywords):
                logger.debug(f"[Personality] Keyword match found for '{question}'")
                return ex["answer"]
        
        return None


# ============================================================================
# 5) GLOBAL LOADER SINGLETON
# ============================================================================
# Global instance
_personality_loader: Optional[PersonalityLoader] = None


def get_personality_loader(examples_dir: str = "examples") -> PersonalityLoader:
    """Get or create global personality loader."""
    # 5.1) Initialize on first access
    global _personality_loader
    if _personality_loader is None:
        _personality_loader = PersonalityLoader(examples_dir)
    return _personality_loader


# ============================================================================
# 6) PHASE 4: PERSONALITY TRANSFORM LAYER
# ============================================================================
# This is a PURE TRANSFORM - it shapes text output AFTER facts are established.
# Personality NEVER touches: intent, execution, memory
# Personality ONLY shapes: text output (cadence, tone, verbosity caps)

import re
from core.config import (
    PersonalityProfile,
    PersonalityGate,
    PERSONALITY_PROFILES,
    DEFAULT_PERSONALITY,
)
from core.intent_parser import IntentType


# 6.1) Intent → Personality Gate Mapping
INTENT_PERSONALITY_GATE = {
    # NONE - No personality allowed (deterministic, system)
    IntentType.SYSTEM_HEALTH: PersonalityGate.NONE,
    IntentType.SYSTEM_STATUS: PersonalityGate.NONE,
    IntentType.SYSTEM_INFO: PersonalityGate.NONE,
    IntentType.TIME_STATUS: PersonalityGate.NONE,
    IntentType.WORLD_TIME: PersonalityGate.NONE,
    IntentType.VOLUME_STATUS: PersonalityGate.NONE,
    IntentType.BLUETOOTH_STATUS: PersonalityGate.NONE,
    IntentType.AUDIO_ROUTING_STATUS: PersonalityGate.NONE,
    IntentType.APP_STATUS: PersonalityGate.NONE,
    IntentType.APP_FOCUS_STATUS: PersonalityGate.NONE,
    
    # MINIMAL - Very light personality touch (actions)
    IntentType.MUSIC: PersonalityGate.MINIMAL,
    IntentType.MUSIC_STOP: PersonalityGate.MINIMAL,
    IntentType.MUSIC_NEXT: PersonalityGate.MINIMAL,
    IntentType.VOLUME_CONTROL: PersonalityGate.MINIMAL,
    IntentType.APP_LAUNCH: PersonalityGate.MINIMAL,
    IntentType.APP_CONTROL: PersonalityGate.MINIMAL,
    IntentType.APP_FOCUS_CONTROL: PersonalityGate.MINIMAL,
    IntentType.BLUETOOTH_CONTROL: PersonalityGate.MINIMAL,
    IntentType.AUDIO_ROUTING_CONTROL: PersonalityGate.MINIMAL,
    
    # FULL - Full personality allowed (questions, explanations)
    IntentType.QUESTION: PersonalityGate.FULL,
    IntentType.GREETING: PersonalityGate.FULL,
    IntentType.ARGO_IDENTITY: PersonalityGate.FULL,
    IntentType.ARGO_GOVERNANCE: PersonalityGate.FULL,
    IntentType.KNOWLEDGE_PHYSICS: PersonalityGate.FULL,
    IntentType.KNOWLEDGE_FINANCE: PersonalityGate.FULL,
    IntentType.KNOWLEDGE_TIME_SYSTEM: PersonalityGate.FULL,
    
    # NEUTRAL - Neutral tone (clarification, errors)
    IntentType.UNKNOWN: PersonalityGate.NEUTRAL,
    IntentType.COMMAND: PersonalityGate.NEUTRAL,
    IntentType.COUNT: PersonalityGate.MINIMAL,
    IntentType.SLEEP: PersonalityGate.MINIMAL,
    IntentType.DEVELOP: PersonalityGate.NEUTRAL,
    IntentType.MUSIC_STATUS: PersonalityGate.MINIMAL,
}


def get_personality_gate(intent_type: Optional[IntentType]) -> str:
    """Get the personality gate level for a given intent type."""
    if intent_type is None:
        return PersonalityGate.NEUTRAL
    return INTENT_PERSONALITY_GATE.get(intent_type, PersonalityGate.NEUTRAL)


def get_active_profile(profile_name: Optional[str] = None) -> PersonalityProfile:
    """Get the active personality profile by name."""
    name = profile_name or DEFAULT_PERSONALITY
    return PERSONALITY_PROFILES.get(name, PERSONALITY_PROFILES["plain"])


# 6.2) Personality Formatter
class PersonalityFormatter:
    """
    Applies personality styling to text responses.
    
    This is a PURE TRANSFORM - it takes completed text and reshapes delivery.
    It does not change facts, only cadence/tone.
    """
    
    def __init__(self, profile: PersonalityProfile, enabled: bool = True):
        self.profile = profile
        self.enabled = enabled
    
    def format(
        self,
        text: str,
        intent_type: Optional[IntentType] = None,
        is_error: bool = False,
        is_clarification: bool = False,
    ) -> str:
        """
        Apply personality transform to response text.
        
        Args:
            text: The factual response to style
            intent_type: The intent that generated this response
            is_error: Whether this is an error message
            is_clarification: Whether this is a clarification request
            
        Returns:
            Styled text (or unchanged if personality disabled/gated)
        """
        if not self.enabled:
            return text
        
        if not text or not text.strip():
            return text
        
        # Get personality gate for this intent
        gate = get_personality_gate(intent_type)
        
        # Apply gating rules
        if gate == PersonalityGate.NONE:
            # No personality - still strip forbidden patterns and follow-ups
            text = self._strip_forbidden(text)
            text = self._strip_follow_up_questions(text)
            return text
        
        if is_error or is_clarification:
            # Errors and clarifications get neutral treatment
            text = self._strip_forbidden(text)
            text = self._strip_follow_up_questions(text)
            return text
        
        if gate == PersonalityGate.MINIMAL:
            # Light touch - just enforce caps and strip forbidden
            text = self._enforce_sentence_cap(text)
            text = self._strip_forbidden(text)
            text = self._strip_follow_up_questions(text)
            return text
        
        if gate == PersonalityGate.NEUTRAL:
            # Neutral - caps, forbidden, no personality additions
            text = self._enforce_sentence_cap(text)
            text = self._strip_forbidden(text)
            text = self._strip_follow_up_questions(text)
            return text
        
        # FULL personality - apply all transforms
        text = self._enforce_sentence_cap(text)
        text = self._strip_forbidden(text)
        text = self._strip_follow_up_questions(text)
        # Note: We don't ADD personality here - the LLM prompt already has tone.
        # We only ENFORCE limits and strip violations.
        
        return text
    
    def _enforce_sentence_cap(self, text: str) -> str:
        """Enforce maximum sentence count."""
        max_sentences = self.profile.max_sentences
        if max_sentences <= 0:
            return text
        
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        if len(sentences) <= max_sentences:
            return text
        
        # Truncate and ensure proper ending
        truncated = ' '.join(sentences[:max_sentences])
        if not truncated.endswith(('.', '!', '?')):
            truncated += '.'
        
        logger.debug(f"[PERSONALITY] Truncated from {len(sentences)} to {max_sentences} sentences")
        return truncated
    
    def _strip_forbidden(self, text: str) -> str:
        """Remove forbidden patterns from text."""
        result = text
        for pattern in self.profile.forbidden_patterns:
            result = re.sub(re.escape(pattern), '', result, flags=re.IGNORECASE)
        # Clean up orphaned punctuation and multiple spaces
        result = re.sub(r'\s*,\s*,', ',', result)  # Double commas
        result = re.sub(r'^\s*,\s*', '', result)   # Leading comma
        result = re.sub(r',\s*\.', '.', result)    # Comma before period
        result = re.sub(r'\s{2,}', ' ', result).strip()
        # Clean up sentences that start with lowercase after stripping
        result = re.sub(r'^\s*[a-z]', lambda m: m.group().upper(), result)
        return result
    
    def _strip_follow_up_questions(self, text: str) -> str:
        """Remove unhelpful follow-up questions if disabled."""
        if not self.profile.no_follow_up_questions:
            return text
        
        follow_up_patterns = [
            r"\bDoes that help\??\s*",
            r"\bDoes that make sense\??\s*",
            r"\bWould you like me to explain more\??\s*",
            r"\bWould you like more details\??\s*",
            r"\bShall I elaborate\??\s*",
            r"\bLet me know if you have questions\.?\s*",
            r"\bLet me know if you need anything else\.?\s*",
            r"\bLet me know if you want something else[\.\!]?\s*",
            r"\bLet me know if you need more details[\.\!]?\s*",
            r"\bIs there anything else\??\s*",
            r"\bAnything else\??\s*",
            r"\bWhat else can I help with\??\s*",
            r"\bHow can I help\??\s*",
            r"\bHow can I help you\??\s*",
            r"\bCan I help with anything else\??\s*",
            r"\bDo you want me to try again\??\s*",
        ]
        
        result = text
        for pattern in follow_up_patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        return result.strip()


# 6.3) Session State
class PersonalityState:
    """Per-session personality state (not persisted)."""
    
    def __init__(self):
        self.enabled: bool = True
        self.active_profile: str = DEFAULT_PERSONALITY
    
    def get_formatter(self) -> PersonalityFormatter:
        """Get a formatter configured with current state."""
        profile = get_active_profile(self.active_profile)
        return PersonalityFormatter(profile, enabled=self.enabled)
    
    def set_profile(self, profile_name: str) -> bool:
        """Set active profile by name. Returns True if valid."""
        if profile_name in PERSONALITY_PROFILES:
            self.active_profile = profile_name
            logger.info(f"[PERSONALITY] Profile set to: {profile_name}")
            return True
        return False
    
    def toggle(self, enabled: Optional[bool] = None) -> bool:
        """Toggle personality on/off. Returns new state."""
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = not self.enabled
        logger.info(f"[PERSONALITY] {'Enabled' if self.enabled else 'Disabled'}")
        return self.enabled


# Global session state (reset on restart)
_personality_state = PersonalityState()


def get_personality_state() -> PersonalityState:
    """Get the global personality state."""
    return _personality_state


def format_response(
    text: str,
    intent_type: Optional[IntentType] = None,
    is_error: bool = False,
    is_clarification: bool = False,
) -> str:
    """
    Convenience function to format a response with current personality settings.
    
    This is the main entry point for the personality system.
    """
    formatter = _personality_state.get_formatter()
    return formatter.format(text, intent_type, is_error, is_clarification)
