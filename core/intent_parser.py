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
    MUSIC_STOP = "music_stop"
    MUSIC_NEXT = "music_next"
    MUSIC_STATUS = "music_status"
    SLEEP = "sleep"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """
    Structured intent extracted from text.
    
    Fields:
    - intent_type: What kind of intent (GREETING, QUESTION, COMMAND, MUSIC, UNKNOWN)
    - confidence: Simple score [0.0, 1.0] (1.0 = high confidence, 0.0 = low)
    - raw_text: Original input text (preserved for debugging)
    - keyword: Optional keyword extracted from command (for MUSIC intents)
    """
    intent_type: IntentType
    confidence: float
    raw_text: str
    keyword: Optional[str] = None
    serious_mode: bool = False

    def __str__(self) -> str:
        """Human-readable representation."""
        keyword_str = f", keyword='{self.keyword}'" if self.keyword else ""
        serious_str = ", serious_mode=true" if self.serious_mode else ""
        return (
            f"Intent({self.intent_type.value}, confidence={self.confidence:.2f}"
            f"{keyword_str}{serious_str}, text='{self.raw_text[:50]}')"
        )


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

        # SERIOUS_MODE keywords (safety / high-stress signals)
        # Presence of these keywords flips self.serious_mode = True
        self.serious_mode_keywords = {
            "death",
            "dying",
            "hurt",
            "sick",
            "panic",
            "failed",
            "lost",
            "broken heart",
            "sad",
            "depression",
            "hard time",
        }

        # SERIOUS_MODE state (per-parse)
        self.serious_mode = False

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

        # Music stop keywords (hard stop, no ambiguity)
        self.music_stop_keywords = {
            "stop",
            "stop music",
            "pause",
        }

        # Music next/skip keywords (hard command, no ambiguity)
        self.music_next_keywords = {
            "next",
            "skip",
            "skip track",
        }

        # Music status/query keywords (read-only status check)
        self.music_status_keywords = {
            "what's playing",
            "what is playing",
            "what song is this",
            "what am i listening to",
        }

        # Music command phrases (must contain these keywords)
        # ZERO-LATENCY TUNED: Extended to include common music requests
        self.music_phrases = {
            "play music",
            "play some music",
            "play something",
            "surprise me",
            "play a song",
            "play",  # Force "play" alone to be treated as music
            "put on",
            "put on some",
            "throw on",
            "queue up",
            "i want",
            "give me",
            "let me hear",
            "play rock",
            "play jazz",
            "play metal",
            "play pop",
            "play classical",
            "play punk",
            "play blues",
            "play hiphop",
            "play rap",
            "play electronic",
            "play david",
            "play bowie",
            "play beatles",
            "play floyd",
            "play zeppelin",
        }

        # Sleep command phrases (high priority, no LLM)
        self.sleep_phrases = {
            "sleep",
            "sleep now",
            "go to sleep",
            "go to sleep now",
            "argo go to sleep",
            "go to sleep argo",
            "that's all",
            "that is all",
        }

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

        text = text.strip()
        text_lower = text.lower()
        first_word = text_lower.split()[0] if text_lower.split() else ""

        # SERIOUS_MODE signal (keyword presence)
        self.serious_mode = any(kw in text_lower for kw in self.serious_mode_keywords)
        serious_mode = self.serious_mode

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
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 1: MUSIC_STOP keywords (highest priority - short-circuit)
        # "stop", "stop music", "pause"
        if any(keyword == text_lower or text_lower.startswith(keyword + " ") for keyword in self.music_stop_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_STOP,
                confidence=1.0,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 2: MUSIC_NEXT keywords (highest priority - short-circuit)
        # "next", "skip", "skip track"
        if any(keyword == text_lower or text_lower.startswith(keyword + " ") for keyword in self.music_next_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_NEXT,
                confidence=1.0,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 3: MUSIC_STATUS keywords (high priority - read-only status query)
        # "what's playing", "what is playing", "what song is this", "what am i listening to"
        if any(keyword == text_lower or keyword in text_lower for keyword in self.music_status_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_STATUS,
                confidence=1.0,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 4: Music phrases or "play" command (high priority - overrides everything)
        # "play music", "play punk", "play something", "surprise me", etc.
        # Also matches variations like "playing", "played", "plays"
        # Extract keyword after "play" if present
        if any(phrase in text_lower for phrase in self.music_phrases) or first_word in {"play", "playing", "played", "plays", "put", "throw", "queue"}:
            keyword = self._extract_music_keyword(text_lower)
            return Intent(
                intent_type=IntentType.MUSIC,
                confidence=0.95,
                raw_text=text,
                keyword=keyword,
                serious_mode=serious_mode,
            )

        # Rule 2: Performance/action words (high priority - overrides questions)
        # "Can you count to five?" should be COMMAND, not QUESTION
        performance_words = {"count", "sing", "recite", "spell", "list", "name"}
        if any(word in text_lower for word in performance_words):
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.9,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 3: Question mark at end (high confidence)
        if text.endswith("?"):
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=1.0,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 4: Starts with question word (medium-high confidence)
        if first_word in self.question_words:
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=0.85,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 5: Starts with greeting keyword (high confidence)
        if first_word in self.greeting_keywords:
            return Intent(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 6: Starts with command word (medium confidence)
        if first_word in self.command_words:
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.75,
                raw_text=text,
                serious_mode=serious_mode,
            )

        # Rule 7: Fallback to unknown (low confidence)
        return Intent(
            intent_type=IntentType.UNKNOWN,
            confidence=0.1,
            raw_text=text,
            serious_mode=serious_mode,
        )

    def _extract_music_keyword(self, text_lower: str) -> Optional[str]:
        """
        Extract keyword after "play" command with normalization.
        
        Normalization includes:
        - Punctuation removal (punctuation, exclamation marks, etc.)
        - Lowercase conversion (already done by caller, but idempotent)
        - Whitespace cleanup (multiple spaces → single space)
        - Filler word removal (music, some, song, a, for, me)
        
        Examples:
        - "play punk!!!" → "punk"
        - "play classic rock???" → "classic rock"
        - "PLAY BOWIE" → "bowie" (already lowercased by caller)
        - "can you play t-rex?" → "t-rex"
        - "play music" → None
        - "play something" → None
        - "surprise me" → None
        
        Args:
            text_lower: Lowercase text
            
        Returns:
            Normalized keyword string, or None if generic
        """
        import string
        
        # Step 1: Remove punctuation
        text_normalized = text_lower.translate(str.maketrans('', '', string.punctuation))
        
        # Step 2: Normalize whitespace (multiple spaces → single space)
        text_normalized = ' '.join(text_normalized.split())
        
        # Remove generic phrases that don't indicate specific genre/keyword
        generic_terms = {"music", "some music", "something", "a song", "a"}
        
        # If text is just "play" followed by generic term, return None
        for generic in generic_terms:
            if text_normalized == f"play {generic}" or text_normalized == f"play some {generic}":
                return None
        
        # Find command anchors and extract everything after them
        words = text_normalized.split()
        play_index = -1

        anchor_phrases = [
            "play",
            "playing",
            "played",
            "plays",
            "put on",
            "throw on",
            "queue up",
            "i want",
            "give me",
            "let me hear",
        ]

        joined = " ".join(words)
        for phrase in anchor_phrases:
            if phrase in joined:
                phrase_words = phrase.split()
                for i in range(len(words) - len(phrase_words) + 1):
                    if words[i:i + len(phrase_words)] == phrase_words:
                        play_index = i + len(phrase_words) - 1
                        break
                if play_index >= 0:
                    break
        
        if play_index >= 0:
            # Get everything after the play word
            keyword_words = words[play_index + 1:]
            
            if keyword_words:
                # Remove common filler words
                filler_words = {"music", "some", "song", "a", "for", "me"}
                keyword_words = [w for w in keyword_words if w not in filler_words]
                
                if keyword_words:
                    return " ".join(keyword_words)
        
        # No keyword extracted
        return None
