"""Per-parser vocabulary and mutable rule state."""

from __future__ import annotations

import logging


class IntentVocabularyMixin:
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
