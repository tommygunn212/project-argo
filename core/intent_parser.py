"""
Intent Parser Module

Responsibility: Convert text to structured intent.
Nothing more.

Does NOT:
- Use LLMs or embeddings (no intelligence)
- Make decisions (rules only)
- Trigger actions (Coordinator's job)
- Maintain memory (stateless)
- Add personality (raw classification)
- Call external services (completely local)
"""

# Debug prints removed to avoid Unicode encoding issues

# ============================================================================
# 1) IMPORTS
# ============================================================================
from core.intent_models import Intent, IntentParser, IntentType
from core.intent_music import IntentMusicMixin
from core.intent_input import apply_phonetic_fixes, normalize_for_rules, strip_wake_prefix
from core.intent_vocabulary import IntentVocabularyMixin
from core.intent_rules.writing import parse_writing_intent
from core.intent_rules.smart_home import parse_smart_home_intent
from core.intent_rules.scheduling import parse_scheduling_intent
from core.intent_rules.vision import parse_vision_intent
from core.intent_rules.filesystem import parse_filesystem_intent
from core.intent_rules.task_plan import parse_task_plan_intent
from core.intent_rules.platform import parse_platform_intent
from core.intent_rules.core_system import (
    ARGO_GOVERNANCE_GATE_PHRASES,
    ARGO_GOVERNANCE_LAW_PHRASES,
    ARGO_IDENTITY_PHRASES,
    FULL_SYSTEM_PHRASES,
    HARDWARE_KEYWORDS,
    SYSTEM_CPU_QUERIES,
    SYSTEM_GPU_QUERIES,
    SYSTEM_MEMORY_QUERIES,
    SYSTEM_MOTHERBOARD_QUERIES,
    SYSTEM_OS_QUERIES,
    parse_full_system_status,
    parse_identity_or_governance,
    parse_system_health,
)
from core.intent_rules.knowledge import parse_knowledge_intent, parse_must_pass_knowledge
from core.intent_rules.general import (
    parse_development_or_tech,
    parse_generic_utterance,
    parse_performance_intent,
)
from core.intent_system_rules import (
    detect_disk_query,
    detect_hardware_info,
    detect_self_diagnostics,
    detect_system_health,
    detect_temperature_query,
    is_system_keyword,
    normalize_system_text,
)

# System and identity keyword banks are re-exported above for compatibility.
# ============================================================================
# 5) DETECTORS / NORMALIZERS
# ============================================================================


# ============================================================================
# 6) INTENT TYPES
# ============================================================================


# ============================================================================
# 9) RULE-BASED PARSER
# ============================================================================
class RuleBasedIntentParser(IntentVocabularyMixin, IntentMusicMixin, IntentParser):

    """
    Simple rule-based intent parser.
    
    Uses hardcoded heuristics to classify text.
    NO LLMs, NO embeddings, NO external services.
    Intentionally dumb for predictability.
    """




    def parse(self, text: str) -> Intent:
        """
        Classify text using hardcoded rules.

        Rules (in priority order):
        1. MUSIC_STOP keywords → MUSIC_STOP (highest - short-circuit)
           - "stop", "stop music", "pause"
        2. MUSIC_NEXT keywords → MUSIC_NEXT (highest - short-circuit)
           - "next", "skip", "skip track"
        3. "play" command (any form) → MUSIC (very high confidence)
           - "play music", "play punk", "play bowie", "surprise me"
           - Extracts keyword if present
        4. Contains performance words (count/sing/recite/spell) → COMMAND (high confidence)
        5. Ends with ? → QUESTION (high confidence)
        6. Starts with question word → QUESTION (medium confidence)
        7. Starts with greeting keyword → GREETING (high confidence)
        8. Starts with command word → COMMAND (medium confidence)
        9. Otherwise → UNKNOWN (low confidence)

        Args:
            text: Raw input text

        Returns:
            Intent with type, confidence, and optional keyword (for MUSIC)

        Raises:
            ValueError: If text is empty
        """
        if not text or not text.strip():
            raise ValueError("text is empty")

        text_original = text.strip()
        text_lower = normalize_for_rules(text_original)

        # SERIOUS_MODE signal (keyword presence) - must be defined before any return
        self.serious_mode = any(kw in text_lower for kw in self.serious_mode_keywords)
        serious_mode = self.serious_mode

        must_pass = parse_must_pass_knowledge(text_original, serious_mode)
        if must_pass is not None:
            return must_pass

        text_lower = apply_phonetic_fixes(text_lower)

        # SERIOUS_MODE signal (keyword presence)
        self.serious_mode = any(kw in text_lower for kw in self.serious_mode_keywords)
        serious_mode = self.serious_mode

        # Rule 0.09: SYSTEM_STATUS (full telemetry) - detect before wake-word stripping
        system_status = parse_full_system_status(text_original, text_lower, serious_mode)
        if system_status is not None:
            return system_status

        prepared = strip_wake_prefix(text_original, text_lower)
        text_original = prepared.original
        text_lower = prepared.normalized
        tokens = prepared.tokens
        first_word = prepared.first_word

        # SERIOUS_MODE signal already computed above

        # Rule -1: SILENCE_OVERRIDE - "shut up" and equivalents (highest priority)
        silence_phrases = {"shut up", "stop talking", "enough", "ok stop", "okay stop", "quiet", "be quiet"}
        if any(phrase in text_lower for phrase in silence_phrases):
            return Intent(
                intent_type=IntentType.SILENCE_OVERRIDE,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=False,  # Never serious mode for this
            )

        # Rule 0: SLEEP keywords (highest priority - short-circuit)
        if (
            text_lower in self.sleep_phrases
            or text_lower.startswith("go to sleep")
            or text_lower == "sleep"
            or text_lower.startswith("sleep ")
        ):
            return Intent(
                intent_type=IntentType.SLEEP,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 0.045: SELF_DIAGNOSTICS - ARGO checks itself (Phase 1)
        if detect_self_diagnostics(text_lower):
            return Intent(
                intent_type=IntentType.SELF_DIAGNOSTICS,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        platform_intent = parse_platform_intent(text_original, text_lower, serious_mode)
        if platform_intent is not None:
            return platform_intent

        identity = parse_identity_or_governance(text_original, text_lower, serious_mode)
        if identity is not None:
            return identity

        writing_intent = parse_writing_intent(text_original, text_lower, serious_mode)
        if writing_intent is not None:
            return writing_intent

        task_plan_intent = parse_task_plan_intent(text_original, text_lower, serious_mode)
        if task_plan_intent is not None:
            return task_plan_intent

        smart_home_intent = parse_smart_home_intent(text_original, text_lower, serious_mode)
        if smart_home_intent is not None:
            return smart_home_intent

        scheduling_intent = parse_scheduling_intent(text_original, text_lower, serious_mode)
        if scheduling_intent is not None:
            return scheduling_intent

        vision_intent = parse_vision_intent(text_original, text_lower, serious_mode)
        if vision_intent is not None:
            return vision_intent

        filesystem_intent = parse_filesystem_intent(text_original, text_lower, serious_mode)
        if filesystem_intent is not None:
            return filesystem_intent

        system_health = parse_system_health(text_original, text_lower, serious_mode)
        if system_health is not None:
            return system_health

        contextual_intent = parse_development_or_tech(
            text_original,
            text_lower,
            serious_mode,
            self.develop_phrases,
            self.tech_keywords,
        )
        if contextual_intent is not None:
            return contextual_intent

        music_intent = self._parse_music_intent(text_original, text_lower, serious_mode)
        if music_intent is not None:
            return music_intent

        performance_intent = parse_performance_intent(text_original, tokens, serious_mode)
        if performance_intent is not None:
            return performance_intent

        knowledge_intent = parse_knowledge_intent(text_original, text_lower, serious_mode)
        if knowledge_intent is not None:
            return knowledge_intent

        return parse_generic_utterance(
            text_original,
            first_word,
            serious_mode,
            self.question_words,
            self.greeting_keywords,
            self.command_words,
        )
