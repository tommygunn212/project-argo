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
    parse_control_intent,
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
from core.intent_rules.router import parse_domain_intent
from core.intent_system_rules import (
    detect_disk_query,
    detect_hardware_info,
    detect_self_diagnostics,
    detect_system_health,
    detect_temperature_query,
    is_system_keyword,
    normalize_system_text,
)
from core.intent_rule_pipeline import parse_intent_rules

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
        return parse_intent_rules(self, text)
