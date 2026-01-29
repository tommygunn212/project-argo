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

# ============================================================================
# 1) IMPORTS
# ============================================================================
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple
import re
import logging

# ============================================================================
# 2) KEYWORD BANKS (MUSIC)
# ============================================================================
MUSIC_FILLER_WORDS = {
    "play", "me", "a", "the", "some", "good", "song", "music", "from",
    "can", "you", "please", "could", "would", "just"
}
MUSIC_MODIFIER_WORDS = {"good", "best", "random", "favorite", "favourite"}
GENERIC_PLAY_PHRASES = {
    "play",
    "play music",
    "play some music",
    "play a song",
    "play some songs",
    "play something",
    "surprise me",
}

# ============================================================================
# 3) KEYWORD BANKS (SYSTEM)
# ============================================================================
SYSTEM_HEALTH_TRIGGERS = [
    "system health",
    "computer health",
    "system status",
    "computer status",
    "how's my system",
    "hows my system",
    "how is my system",
    "how is my system doing",
    "system check",
    "gpu health",
    "cpu health",
    "system gpu health",
    "system cpu health",
    "disk space",
    "free space",
]
FULL_SYSTEM_PHRASES = [
    "full system",
    "full status",
    "full report",
    "complete status",
    "everything",
    "all system info",
    "all system information",
    "all computer info",
    "all computer information",
    "everything about my computer",
]

SYSTEM_KEYWORDS = {
    "how much memory do i have",
    "total memory",
    "installed memory",
    "ram size",
    "what cpu do i have",
    "cpu model",
    "cpu name",
    "what processor do i have",
    "processor model",
    "processor name",
    "what gpu do i have",
    "gpu model",
    "gpu name",
    "graphics card",
    "video card",
    "graphics",
    "system specs",
    "hardware",
    "operating system",
    "os version",
    "windows version",
    "what os",
    "what operating system",
    "gpu health",
    "cpu health",
    "system health",
    "system status",
    "computer status",
    "disk space",
    "free space",
    "memory usage",
    "how much space do i have",
    "which drive has the most free space",
    "what drive is the fullest",
}

HARDWARE_KEYWORDS = [
    "memory", "ram", "cpu", "processor",
    "gpu", "graphics", "video card",
    "system specs", "hardware",
    "motherboard", "mainboard",
]

SYSTEM_MEMORY_QUERIES = [
    "how much memory do i have",
    "total memory",
    "installed memory",
    "ram size",
    "memory usage",
]

SYSTEM_CPU_QUERIES = [
    "what cpu do i have",
    "cpu model",
    "cpu name",
    "what processor do i have",
    "processor model",
    "processor name",
]

SYSTEM_GPU_QUERIES = [
    "what gpu do i have",
    "gpu model",
    "gpu name",
    "graphics card",
    "video card",
    "graphics",
]

SYSTEM_OS_QUERIES = [
    "operating system",
    "os version",
    "windows version",
    "what os",
    "what operating system",
    "what system am i running",
    "what system am i on",
    "what os am i running",
    "which os",
    "which operating system",
]

SYSTEM_MOTHERBOARD_QUERIES = [
    "what motherboard",
    "motherboard",
    "mainboard",
]

SYSTEM_NORMALIZE = {
    "gpu health": "system gpu health",
    "cpu health": "system cpu health",
    "disk": "disk space",
}

# ============================================================================
# 4) KEYWORD BANKS (TEMPERATURE)
# ============================================================================
TEMP_KEYWORDS = [
    "temperature",
    "temp",
    "hot",
    "overheating",
    "heat",
    "thermal",
    "thermals",
]

DISK_QUERY_PHRASES = [
    "drive",
    "drives",
    "disk",
    "disks",
    "free space",
    "disk space",
    "storage",
    "fullest",
    "most free",
    "most space",
    "how much space",
]


# ============================================================================
# 5) DETECTORS / NORMALIZERS
# ============================================================================
def detect_system_health(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in SYSTEM_HEALTH_TRIGGERS)


def detect_temperature_query(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in TEMP_KEYWORDS)


def detect_disk_query(text: str) -> bool:
    t = text.lower()
    if re.search(r"\b[a-z]\s*drive\b", t):
        return True
    if re.search(r"\b[a-z]:\b", t):
        return True
    return any(k in t for k in DISK_QUERY_PHRASES)


def normalize_system_text(text: str) -> str:
    t = text.lower().strip()
    return SYSTEM_NORMALIZE.get(t, t)


def is_system_keyword(text: str) -> bool:
    t = text.lower().strip()
    return t in SYSTEM_KEYWORDS or detect_disk_query(t)


# ============================================================================
# 6) INTENT TYPES
# ============================================================================
class IntentType(Enum):
    """Supported intent classifications."""
    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    COUNT = "count"
    MUSIC = "music"
    MUSIC_STOP = "music_stop"
    MUSIC_NEXT = "music_next"
    MUSIC_STATUS = "music_status"
    SLEEP = "sleep"
    SYSTEM_HEALTH = "system_health"
    SYSTEM_INFO = "system_info"
    DEVELOP = "develop"
    UNKNOWN = "unknown"


# ============================================================================
# 7) INTENT STRUCTURE
# ============================================================================
@dataclass
class Intent:
    """
    Structured intent extracted from text.
    
    Fields:
    - intent_type: What kind of intent (GREETING, QUESTION, COMMAND, MUSIC, UNKNOWN)
    - confidence: Simple score [0.0, 1.0] (1.0 = high confidence, 0.0 = low)
    - raw_text: Original input text (preserved for debugging)
    - keyword: Optional keyword extracted from command (for MUSIC intents)
    - artist: Optional artist extracted (for MUSIC intents)
    - title: Optional title extracted (for MUSIC intents)
    - modifiers: Optional modifiers extracted (for MUSIC intents)
    - is_generic_play: True if intent is a generic play request
    """
    intent_type: IntentType
    confidence: float
    raw_text: str
    keyword: Optional[str] = None
    artist: Optional[str] = None
    title: Optional[str] = None
    modifiers: Optional[List[str]] = None
    is_generic_play: bool = False
    serious_mode: bool = False
    unresolved: bool = False
    subintent: Optional[str] = None
    explicit_genre: bool = False

    def __str__(self) -> str:
        """Human-readable representation."""
        keyword_str = f", keyword='{self.keyword}'" if self.keyword else ""
        artist_str = f", artist='{self.artist}'" if self.artist else ""
        title_str = f", title='{self.title}'" if self.title else ""
        modifiers_str = f", modifiers={self.modifiers}" if self.modifiers else ""
        generic_str = ", generic_play=true" if self.is_generic_play else ""
        serious_str = ", serious_mode=true" if self.serious_mode else ""
        subintent_str = f", subintent={self.subintent}" if self.subintent else ""
        return (
            f"Intent({self.intent_type.value}, confidence={self.confidence:.2f}"
            f"{keyword_str}{artist_str}{title_str}{modifiers_str}{generic_str}{serious_str}{subintent_str}, text='{self.raw_text[:50]}')"
        )


# ============================================================================
# 8) INTENT PARSER INTERFACE
# ============================================================================
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


# ============================================================================
# 9) RULE-BASED PARSER
# ============================================================================
class RuleBasedIntentParser(IntentParser):
    """
    Simple rule-based intent parser.
    
    Uses hardcoded heuristics to classify text.
    NO LLMs, NO embeddings, NO external services.
    Intentionally dumb for predictability.
    """

    def __init__(self):
        """Initialize hardcoded rules."""
        self.logger = logging.getLogger(__name__)
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

        # Development/build intent keywords
        self.develop_phrases = {
            "build a tool",
            "write a script",
            "create an app",
            "code a feature",
            "draft a plugin",
        }

        # Technical keywords (force QUESTION/DEVELOP, never MUSIC)
        self.tech_keywords = {
            "3950x",
            "cpu",
            "gpu",
            "ram",
            "rtx",
            "upgrade",
            "motherboard",
            "sandbox",
            "python",
            "script",
            "klipper",
            "e3d",
            "revo",
        }

        # Known music genres (used to validate "play <genre>")
        self.music_genres = {
            "rock",
            "jazz",
            "metal",
            "pop",
            "classical",
            "punk",
            "blues",
            "hiphop",
            "rap",
            "electronic",
            "country",
            "folk",
            "disco",
            "funk",
            "reggae",
            "soul",
            "rnb",
            "indie",
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

        text_original = text.strip()
        text_lower = normalize_system_text(text_original.lower())

        # Phonetic fixes for common mishears
        phonetic_fixes = {
            "porcupine": "argo",
            "pocket point": "argo",
            "pocketpoint": "argo",
            "led like": "led light",
            "ducts": "ducks",
        }
        for mistake, fix in phonetic_fixes.items():
            text_lower = text_lower.replace(mistake, fix)

        # Strip wake word prefix (e.g., "argo, ...") from parsing logic
        text_lower = re.sub(r"^(argo[\s,]+)+", "", text_lower).strip()
        text_original = re.sub(r"^(argo[\s,]+)+", "", text_original, flags=re.IGNORECASE).strip()
        text = text_original
        tokens = re.findall(r"[a-z0-9']+", text_lower)
        first_word = tokens[0] if tokens else ""

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
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 0.05: SYSTEM_HEALTH temperature queries (hard deterministic)
        if detect_temperature_query(text_lower):
            return Intent(
                intent_type=IntentType.SYSTEM_HEALTH,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
                subintent="temperature",
            )

        # Rule 0.06: SYSTEM_HEALTH disk queries (hard deterministic)
        if detect_disk_query(text_lower):
            return Intent(
                intent_type=IntentType.SYSTEM_HEALTH,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
                subintent="disk",
            )

        # Rule 0.1: SYSTEM_HEALTH hardware queries (hard deterministic)
        if any(k in text_lower for k in HARDWARE_KEYWORDS) or any(q in text_lower for q in SYSTEM_OS_QUERIES):
            subintent = None
            if any(q in text_lower for q in SYSTEM_MEMORY_QUERIES):
                subintent = "memory"
            elif any(q in text_lower for q in SYSTEM_CPU_QUERIES):
                subintent = "cpu"
            elif any(q in text_lower for q in SYSTEM_GPU_QUERIES):
                subintent = "gpu"
            elif any(q in text_lower for q in SYSTEM_OS_QUERIES):
                subintent = "os"
            elif any(q in text_lower for q in SYSTEM_MOTHERBOARD_QUERIES):
                subintent = "motherboard"
            else:
                subintent = "hardware"
            return Intent(
                intent_type=IntentType.SYSTEM_HEALTH,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
                subintent=subintent,
            )

        # Rule 0.25: SYSTEM_HEALTH keywords (hard deterministic, no LLM)
        if detect_system_health(text_lower) or any(p in text_lower for p in FULL_SYSTEM_PHRASES):
            subintent = "full" if any(p in text_lower for p in FULL_SYSTEM_PHRASES) else None
            return Intent(
                intent_type=IntentType.SYSTEM_HEALTH,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
                subintent=subintent,
            )

        # Rule 0.5: DEVELOP keywords (high priority - developer context)
        if any(phrase in text_lower for phrase in self.develop_phrases):
            return Intent(
                intent_type=IntentType.DEVELOP,
                confidence=0.98,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Tech keyword override: force QUESTION for hardware/technical queries
        if any(keyword in text_lower for keyword in self.tech_keywords):
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=0.9,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 1: MUSIC_STOP keywords (highest priority - short-circuit)
        # "stop", "stop music", "pause"
        if any(keyword == text_lower or text_lower.startswith(keyword + " ") for keyword in self.music_stop_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_STOP,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 2: MUSIC_NEXT keywords (highest priority - short-circuit)
        # "next", "skip", "skip track"
        if any(keyword == text_lower or text_lower.startswith(keyword + " ") for keyword in self.music_next_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_NEXT,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 3: MUSIC_STATUS keywords (high priority - read-only status query)
        # "what's playing", "what is playing", "what song is this", "what am i listening to"
        if any(keyword == text_lower or keyword in text_lower for keyword in self.music_status_keywords):
            return Intent(
                intent_type=IntentType.MUSIC_STATUS,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 4: Music intent (disambiguated)
        # Only trigger if music-specific terms are present (play/music/song) and no tech keywords
        music_terms = {"music", "song", "artist", "album"}
        has_play = "play" in text_lower
        has_music_term = any(term in text_lower for term in music_terms)
        has_genre_play = any(f"play {genre}" in text_lower for genre in self.music_genres)
        if (has_play or has_music_term) and not any(keyword in text_lower for keyword in self.tech_keywords):
            artist, title, modifiers = self._extract_music_components(text_original, text_lower)
            keyword = title or artist or self._extract_music_keyword(text_lower)
            is_generic_play = False
            if not artist and not title and not keyword:
                normalized_phrase = " ".join(re.findall(r"[a-z0-9']+", text_lower)).strip()
                is_generic_play = normalized_phrase in GENERIC_PLAY_PHRASES
            self.logger.debug(
                "[INTENT] artist=\"%s\" title=%s modifiers=%s",
                artist,
                f"\"{title}\"" if title else "None",
                modifiers or [],
            )
            return Intent(
                intent_type=IntentType.MUSIC,
                confidence=0.95,
                raw_text=text_original,
                keyword=keyword,
                artist=artist,
                title=title,
                modifiers=modifiers or [],
                is_generic_play=is_generic_play,
                serious_mode=serious_mode,
                explicit_genre=has_genre_play,
            )

        # Rule 4.5: COUNT intent (deterministic, no LLM)
        if "count" in tokens:
            return Intent(
                intent_type=IntentType.COUNT,
                confidence=0.9,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 2: Performance/action words (high priority - overrides questions)
        # "Can you count to five?" should be COMMAND, not QUESTION
        performance_words = {"count", "sing", "recite", "spell", "list", "name"}
        if any(word in tokens for word in performance_words):
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.9,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 3: Question mark present (high confidence)
        if "?" in text:
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 4: Starts with question word (medium-high confidence)
        if first_word in self.question_words:
            return Intent(
                intent_type=IntentType.QUESTION,
                confidence=0.85,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 5: Starts with greeting keyword (high confidence)
        if first_word in self.greeting_keywords:
            return Intent(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 6: Starts with command word (medium confidence)
        if first_word in self.command_words:
            return Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.75,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        # Rule 7: Fallback to unknown (low confidence)
        return Intent(
            intent_type=IntentType.UNKNOWN,
            confidence=0.1,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    def _extract_music_components(
        self,
        text_original: str,
        text_lower: str,
    ) -> Tuple[Optional[str], Optional[str], List[str]]:
        original = self._strip_music_anchors(text_original)
        lower = original.lower()

        match = re.search(r"\b(from|by)\b", original, flags=re.IGNORECASE)
        artist = None
        title = None
        modifiers: List[str] = []

        if match:
            before_original = original[:match.start()].strip()
            after_original = original[match.end():].strip()
            if after_original:
                artist = self._clean_artist_candidate(after_original)

            title, modifiers = self._split_title_and_modifiers(before_original)
            return artist, title, modifiers

        title, modifiers = self._split_title_and_modifiers(original)
        return artist, title, modifiers

    def _strip_music_anchors(self, text_original: str) -> str:
        anchors = [
            "can you play",
            "could you play",
            "would you play",
            "please play",
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
        stripped = text_original.strip()
        for phrase in anchors:
            pattern = r"^\s*" + re.escape(phrase) + r"\b"
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE).strip()
                break
        return stripped

    def _split_title_and_modifiers(self, text_original: str) -> Tuple[Optional[str], List[str]]:
        if not text_original:
            return None, []
        original_tokens = re.findall(r"[A-Za-z0-9']+", text_original)
        lower_tokens = [token.lower() for token in original_tokens]

        filtered_tokens = [
            (orig, low)
            for orig, low in zip(original_tokens, lower_tokens)
            if low not in MUSIC_FILLER_WORDS
        ]

        title_tokens: List[str] = []
        modifiers: List[str] = []
        for orig, low in filtered_tokens:
            if low in MUSIC_MODIFIER_WORDS:
                modifiers.append(low)
            else:
                title_tokens.append(orig)

        title = " ".join(title_tokens).strip() if title_tokens else None
        return title, modifiers

    def _clean_artist_candidate(self, artist_text: str) -> Optional[str]:
        if not artist_text:
            return None
        tokens = re.findall(r"[A-Za-z0-9']+", artist_text)
        cleaned_tokens = [
            token
            for token in tokens
            if token.lower() not in MUSIC_FILLER_WORDS and token.lower() not in {"by", "from"}
        ]
        cleaned = " ".join(cleaned_tokens).strip()
        return cleaned or None

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
            "can you play",
            "could you play",
            "would you play",
            "please play",
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
                filler_words = {"music", "some", "song", "a", "for", "me", "can", "you", "please", "could", "would", "just"}
                keyword_words = [w for w in keyword_words if w not in filler_words]
                
                if keyword_words:
                    return " ".join(keyword_words)
        
        # No keyword extracted
        return None
