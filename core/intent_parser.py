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

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IntentType(Enum):
    """Supported intent classifications."""
    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    MUSIC = "music"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """
    Structured intent extracted from text.
    
    Fields:
    - intent_type: What kind of intent (GREETING, QUESTION, COMMAND, UNKNOWN)
    - confidence: Simple score [0.0, 1.0] (1.0 = high confidence, 0.0 = low)
    - raw_text: Original input text (preserved for debugging)
    """
    intent_type: IntentType
    confidence: float
    raw_text: str

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"Intent({self.intent_type.value}, confidence={self.confidence:.2f}, text='{self.raw_text[:50]}')"


class IntentParser(ABC):
    """
    Base class for intent parsers.
    
    Single responsibility: Classify text into structured intents.
    """

    @abstractmethod
    def parse(self, text: str) -> Intent:
        """
        Parse text into structured intent.

        Args:
            text: Raw user input (from transcription)

        Returns:
            Intent object with type, confidence, and original text

        Raises:
            ValueError: If text is empty
        """
        pass


class RuleBasedIntentParser(IntentParser):
    """
    Simple rule-based intent parser.
    
    Uses hardcoded heuristics to classify text.
    NO LLMs, NO embeddings, NO external services.
    Intentionally dumb for predictability.
    """

    def __init__(self):
        """Initialize hardcoded rules."""
        # Greeting keywords (case-insensitive)
        self.greeting_keywords = {
            "hello",
            "hi",
            "hey",
            "greetings",
            "good morning",
            "good afternoon",
            "good evening",
            "howdy",
            "what's up",
        }

        # Question indicators
        self.question_indicators = {"?"}

        # Question words
        self.question_words = {
            "what",
            "how",
            "why",
            "when",
            "where",
            "who",
            "which",
            "is",
            "are",
            "can",
            "could",
            "would",
            "should",
            "do",
            "does",
            "did",
        }

        # Command indicators (imperative verbs)
        self.command_words = {
            "play",
            "stop",
            "start",
            "turn",
            "set",
            "open",
            "close",
            "get",
            "show",
            "tell",
            "find",
            "search",
            "call",
            "send",
            "create",
            "make",
            "do",
            "run",
            "count",
            "list",
            "name",
            "sing",
            "recite",
            "spell",
        }

        # Music command phrases (must contain these keywords)
        self.music_phrases = {
            "play music",
            "play some music",
            "play something",
            "surprise me",
            "play a song",
        }

    def parse(self, text: str) -> Intent:
        """
        Classify text using hardcoded rules.

        Rules (in priority order):
        1. Music phrases (exact match) → MUSIC (very high confidence)
        2. Contains performance words (count/sing/recite/spell) → COMMAND (high confidence)
        3. Ends with ? → QUESTION (high confidence)
        4. Starts with question word → QUESTION (medium confidence)
        5. Starts with greeting keyword → GREETING (high confidence)
        6. Starts with command word → COMMAND (medium confidence)
        7. Otherwise → UNKNOWN (low confidence)

        Args:
            text: Raw input text

        Returns:
            Intent with type and confidence

        Raises:
            ValueError: If text is empty
        """
        if not text or not text.strip():
            raise ValueError("text is empty")

        text = text.strip()
        text_lower = text.lower()
        first_word = text_lower.split()[0] if text_lower.split() else ""

        # Rule 1: Music phrases (highest priority - overrides everything)
        # "play music", "play some music", "surprise me", etc.
        if any(phrase in text_lower for phrase in self.music_phrases):
            return Intent(
                intent_type=IntentType.MUSIC,
                confidence=0.95,
                raw_text=text,
            )

        # Rule 2: Performance/action words (high priority - overrides questions)
        # "Can you count to five?" should be COMMAND, not QUESTION
        performance_words = {"count", "sing", "recite", "spell", "list", "name"}
        if any(word in text_lower for word in performance_words):
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.9,
                raw_text=text,
            )

        # Rule 3: Question mark at end (high confidence)
        if text.endswith("?"):
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=1.0,
                raw_text=text,
            )

        # Rule 4: Starts with question word (medium-high confidence)
        if first_word in self.question_words:
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=0.85,
                raw_text=text,
            )

        # Rule 5: Starts with greeting keyword (high confidence)
        if first_word in self.greeting_keywords:
            return Intent(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                raw_text=text,
            )

        # Rule 6: Starts with command word (medium confidence)
        if first_word in self.command_words:
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.75,
                raw_text=text,
            )

        # Rule 7: Fallback to unknown (low confidence)
        return Intent(
            intent_type=IntentType.UNKNOWN,
            confidence=0.1,
            raw_text=text,
        )
