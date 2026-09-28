"""Music parsing helpers for the rule-based intent parser."""

from __future__ import annotations

import re
import string
from typing import List, Optional, Tuple

from core.intent_models import Intent, IntentType


GENERIC_PLAY_PHRASES = {
    "play",
    "play music",
    "play some music",
    "play a song",
    "play some songs",
    "play something",
    "surprise me",
}

MUSIC_FILLER_WORDS = {
    "play", "me", "a", "the", "some", "good", "song", "music", "from",
    "can", "you", "please", "could", "would", "just", "something"
}
MUSIC_MODIFIER_WORDS = {"good", "best", "random", "favorite", "favourite"}


class IntentMusicMixin:
    def _parse_music_intent(
        self,
        text_original: str,
        text_lower: str,
        serious_mode: bool,
    ) -> Optional[Intent]:
        """Classify transport, status, and play requests in priority order."""
        if any(
            keyword == text_lower or text_lower.startswith(keyword + " ")
            for keyword in self.music_stop_keywords
        ):
            return Intent(
                intent_type=IntentType.MUSIC_STOP,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        if any(
            keyword == text_lower or text_lower.startswith(keyword + " ")
            for keyword in self.music_next_keywords
        ):
            return Intent(
                intent_type=IntentType.MUSIC_NEXT,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        if any(
            keyword == text_lower or keyword in text_lower
            for keyword in self.music_status_keywords
        ):
            return Intent(
                intent_type=IntentType.MUSIC_STATUS,
                confidence=1.0,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

        normalized_phrase = " ".join(re.findall(r"[a-z0-9']+", text_lower)).strip()
        music_terms = {"music", "song", "artist", "album"}
        has_play = "play" in text_lower
        has_music_term = any(term in text_lower for term in music_terms)
        has_genre_play = any(f"play {genre}" in text_lower for genre in self.music_genres)
        is_generic_play_phrase = normalized_phrase in GENERIC_PLAY_PHRASES
        if not (has_play or has_music_term or is_generic_play_phrase):
            return None
        if any(keyword in text_lower for keyword in self.tech_keywords):
            return None

        artist, title, modifiers = self._extract_music_components(text_original, text_lower)
        keyword = title or artist or self._extract_music_keyword(text_lower)
        if keyword:
            keyword = keyword.lower()
        is_generic_play = False
        if is_generic_play_phrase:
            artist = None
            title = None
            keyword = None
        if not artist and not title and not keyword:
            is_generic_play = normalized_phrase in GENERIC_PLAY_PHRASES
        self.logger.debug(
            '[INTENT] artist="%s" title=%s modifiers=%s',
            artist,
            f'"{title}"' if title else "None",
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
