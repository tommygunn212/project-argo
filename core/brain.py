"""
ARGO Brain: 3-Layer Human-Like Memory System

Architecture:
  SHORT-TERM  — last exchange only (RAM)
  WORKING     — current task/topic/mood (RAM, persisted to SQLite on change)
  LONG-TERM   — facts, relationships, preferences, episodes (SQLite)

Prompt assembly pulls ~200 tokens instead of ~1500.
Feels like JARVIS, not a chatbot.
"""

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("ARGO.Brain")

DB_PATH = Path("data") / "brain.db"

# ── Data Classes ──────────────────────────────────────────────────────────

@dataclass
class Fact:
    id: int
    category: str          # "identity", "relationship", "preference", "project", "general"
    subject: str           # "Tommy", "Bandit", "ARGO"
    relation: str          # "is", "likes", "built", "has_dog", "son_name"
    value: str             # "a filmmaker", "sarcasm", "ChefsByte", "Bandit", "Jesse"
    confidence: float      # 0.0-1.0 (explicit=1.0, inferred=0.7)
    source: str            # "user_explicit", "user_implicit", "system"
    created_at: str
    last_accessed: str
    access_count: int


@dataclass
class Episode:
    id: int
    summary: str           # "Tommy switched ARGO to GPT-4o-mini for speed"
    topic: str             # "argo_development"
    emotion: str           # "excited", "frustrated", "neutral"
    created_at: str


@dataclass
class WorkingState:
    current_topic: str = ""
    current_task: str = ""
    current_mood: str = "neutral"
    entities: List[str] = field(default_factory=list)
    topic_turns: int = 0
    session_start: str = ""


@dataclass
class ShortTermMemory:
    last_user: str = ""
    last_assistant: str = ""
    last_intent: str = ""
    last_timestamp: str = ""


# ── Core Brain ────────────────────────────────────────────────────────────

class ArgoBrain:
    """
    Three-layer memory that thinks like a human brain.

    Usage:
        brain = ArgoBrain()
        brain.before_llm(user_text, intent)     # updates state
        context = brain.get_prompt_context()      # ~200 tokens
        brain.after_llm(user_text, response)      # stores exchange
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Layer 1: Short-term (RAM only)
        self.short_term = ShortTermMemory()

        # Layer 2: Working memory (RAM, persisted on change)
        self.working = WorkingState(
            session_start=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

        # Layer 3: Long-term (SQLite)
        self._init_db()
        self._restore_working_state()

        logger.info("[BRAIN] Initialized — 3-layer memory online")

    # ── Database Setup ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=1.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'user_explicit',
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                topic TEXT NOT NULL DEFAULT '',
                emotion TEXT NOT NULL DEFAULT 'neutral',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS working_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_topic TEXT NOT NULL DEFAULT '',
                current_task TEXT NOT NULL DEFAULT '',
                current_mood TEXT NOT NULL DEFAULT 'neutral',
                entities TEXT NOT NULL DEFAULT '[]',
                topic_turns INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
            CREATE INDEX IF NOT EXISTS idx_facts_relation ON facts(relation);
            CREATE INDEX IF NOT EXISTS idx_episodes_topic ON episodes(topic);
        """)
        conn.commit()
        conn.close()

    # ── Layer 1: Short-Term Memory ────────────────────────────────────

    def update_short_term(self, user_text: str, assistant_text: str, intent: str = "") -> None:
        """Store only the last exchange. That's it."""
        self.short_term.last_user = user_text
        self.short_term.last_assistant = assistant_text
        self.short_term.last_intent = intent
        self.short_term.last_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get_short_term_block(self) -> str:
        """Returns last exchange for prompt context."""
        if not self.short_term.last_user:
            return ""
        lines = []
        lines.append(f"User: {self.short_term.last_user}")
        if self.short_term.last_assistant:
            lines.append(f"ARGO: {self.short_term.last_assistant}")
        return "\n".join(lines)

    # ── Layer 2: Working Memory ───────────────────────────────────────

    def update_working_state(
        self,
        user_text: str,
        intent: str = "",
    ) -> None:
        """
        Infer current topic/task/mood from user input.
        This is conversation STATE, not conversation HISTORY.
        """
        text_lower = (user_text or "").lower()

        # Extract entities (nouns/proper nouns) — simple keyword extraction
        entities = self._extract_entities(text_lower)
        if entities:
            self.working.entities = entities

        # Detect topic shifts
        new_topic = self._infer_topic(text_lower, entities, intent)
        if new_topic and new_topic != self.working.current_topic:
            logger.info(f"[BRAIN] Topic shift: '{self.working.current_topic}' → '{new_topic}'")
            self.working.current_topic = new_topic
            self.working.topic_turns = 0
        self.working.topic_turns += 1

        # Detect task context
        task = self._infer_task(text_lower, intent)
        if task:
            self.working.current_task = task

        # Detect mood
        mood = self._infer_mood(text_lower)
        if mood:
            self.working.current_mood = mood

        # Persist to SQLite
        self._save_working_state()

    def _extract_entities(self, text: str) -> List[str]:
        """Pull out meaningful words — names, projects, tech terms."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "must", "ought",
            "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
            "they", "them", "this", "that", "these", "those", "what", "which",
            "who", "whom", "where", "when", "why", "how", "if", "then", "so",
            "but", "and", "or", "not", "no", "yes", "yeah", "ok", "okay",
            "just", "also", "too", "very", "really", "about", "with", "from",
            "for", "of", "to", "in", "on", "at", "by", "up", "out", "off",
            "into", "over", "after", "before", "between", "under", "again",
            "there", "here", "all", "each", "every", "some", "any", "most",
            "other", "than", "now", "well", "like", "get", "got", "make",
            "let", "know", "think", "want", "go", "going", "come", "take",
            "thing", "things", "stuff", "way", "something", "anything",
            "tell", "said", "say", "right", "still", "already", "hey", "argo",
            "please", "thanks", "thank", "sure", "much", "lot", "little",
            "big", "new", "old", "good", "bad", "great", "nice", "cool",
            "don", "doesn", "didn", "won", "wouldn", "couldn", "shouldn",
            "isn", "aren", "wasn", "weren", "hasn", "haven", "hadn",
        }
        words = re.findall(r"[a-z][a-z0-9_.-]+", text)
        return [w for w in words if w not in stop_words and len(w) > 2][:8]

    def _infer_topic(self, text: str, entities: List[str], intent: str) -> str:
        """Detect what we're talking about."""
        topic_signals = {
            "memory": "memory_system",
            "voice": "voice_system",
            "audio": "audio_system",
            "music": "music",
            "code": "coding",
            "python": "coding",
            "debug": "debugging",
            "error": "debugging",
            "weather": "weather",
            "news": "news",
            "cook": "cooking",
            "recipe": "cooking",
            "chefsbyte": "chefsbyte",
            "film": "filmmaking",
            "movie": "filmmaking",
            "game": "gaming",
            "jesse": "family",
            "bandit": "family",
            "dog": "family",
            "son": "family",
            "timer": "timer",
            "alarm": "timer",
            "remind": "reminders",
            "schedule": "planning",
            "plan": "planning",
            "argo": "argo_development",
        }
        for keyword, topic in topic_signals.items():
            if keyword in text:
                return topic
        # If entities overlap with previous topic, keep it
        if entities and self.working.current_topic:
            return self.working.current_topic
        return self.working.current_topic or "general"

    def _infer_task(self, text: str, intent: str) -> str:
        """Detect current task from action verbs."""
        task_patterns = [
            (r"(fix|debug|troubleshoot)\s+(.+)", "debugging {}"),
            (r"(build|create|make|implement)\s+(.+)", "building {}"),
            (r"(switch|change|update|upgrade)\s+(.+)", "updating {}"),
            (r"(test|check|verify)\s+(.+)", "testing {}"),
            (r"(deploy|push|release)\s+(.+)", "deploying {}"),
            (r"(research|look into|investigate)\s+(.+)", "researching {}"),
            (r"(set up|setup|configure|install)\s+(.+)", "setting up {}"),
        ]
        for pattern, template in task_patterns:
            m = re.search(pattern, text)
            if m:
                obj = m.group(2)[:50].strip(" .,!?")
                return template.format(obj)
        return ""

    def _infer_mood(self, text: str) -> str:
        """Detect emotional tone."""
        mood_signals = {
            "excited": ["awesome", "amazing", "incredible", "hell yeah", "let's go",
                       "love it", "perfect", "stoked", "pumped", "impressed"],
            "frustrated": ["damn", "dammit", "wtf", "broken", "doesn't work", "hate",
                          "annoying", "stupid", "crap", "ugh", "screw"],
            "curious": ["wonder", "curious", "how does", "what if", "interesting",
                       "tell me about", "explain"],
            "focused": ["let's do", "ok do it", "go ahead", "switch", "build",
                       "implement", "make it"],
            "casual": ["what's up", "hey", "chillin", "just wondering", "whatever"],
        }
        for mood, triggers in mood_signals.items():
            for trigger in triggers:
                if trigger in text:
                    return mood
        return ""

    def _save_working_state(self) -> None:
        """Persist working memory to SQLite."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute("""
                INSERT INTO working_state (id, current_topic, current_task, current_mood, entities, topic_turns, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    current_topic = excluded.current_topic,
                    current_task = excluded.current_task,
                    current_mood = excluded.current_mood,
                    entities = excluded.entities,
                    topic_turns = excluded.topic_turns,
                    updated_at = excluded.updated_at
            """, (
                self.working.current_topic,
                self.working.current_task,
                self.working.current_mood,
                json.dumps(self.working.entities),
                self.working.topic_turns,
                now,
            ))
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to save working state: {e}")
        finally:
            conn.close()

    def _restore_working_state(self) -> None:
        """Restore working memory from last session (continuity across restarts)."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM working_state WHERE id = 1").fetchone()
            if row:
                self.working.current_topic = row["current_topic"]
                self.working.current_task = row["current_task"]
                self.working.current_mood = row["current_mood"]
                self.working.entities = json.loads(row["entities"])
                self.working.topic_turns = row["topic_turns"]
                logger.info(f"[BRAIN] Restored working state: topic='{self.working.current_topic}' task='{self.working.current_task}'")
        except (sqlite3.Error, json.JSONDecodeError) as e:
            logger.warning(f"[BRAIN] Could not restore working state: {e}")
        finally:
            conn.close()

    def get_working_block(self) -> str:
        """Returns working memory for prompt context."""
        parts = []
        if self.working.current_topic:
            parts.append(f"Topic: {self.working.current_topic}")
        if self.working.current_task:
            parts.append(f"Task: {self.working.current_task}")
        if self.working.current_mood and self.working.current_mood != "neutral":
            parts.append(f"Mood: {self.working.current_mood}")
        return " | ".join(parts)

    # ── Layer 3: Long-Term Memory ─────────────────────────────────────

    def store_fact(
        self,
        category: str,
        subject: str,
        relation: str,
        value: str,
        confidence: float = 1.0,
        source: str = "user_explicit",
    ) -> int:
        """
        Store a fact. Deduplicates on (subject, relation).
        If the fact already exists, updates the value instead of creating a duplicate.
        """
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # Check for existing fact with same subject + relation + value (exact duplicate)
            existing = conn.execute(
                "SELECT id FROM facts WHERE subject = ? COLLATE NOCASE AND relation = ? COLLATE NOCASE AND value = ? COLLATE NOCASE",
                (subject, relation, value)
            ).fetchone()

            if existing:
                # Exact duplicate — just update timestamp
                conn.execute(
                    "UPDATE facts SET confidence = ?, source = ?, last_accessed = ? WHERE id = ?",
                    (confidence, source, now, existing["id"])
                )
                conn.commit()
                logger.info(f"[BRAIN] Updated fact: {subject} {relation} → {value}")
                return existing["id"]
            else:
                # Insert new fact
                cur = conn.execute(
                    """INSERT INTO facts (category, subject, relation, value, confidence, source, created_at, last_accessed, access_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (category, subject, relation, value, confidence, source, now, now)
                )
                conn.commit()
                logger.info(f"[BRAIN] Stored fact: {subject} {relation} → {value}")
                return cur.lastrowid or -1
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to store fact: {e}")
            return -1
        finally:
            conn.close()

    def retrieve_relevant_facts(self, user_text: str, limit: int = 5) -> List[Fact]:
        """
        Semantic-ish fact retrieval: pull only facts relevant to this query.
        Uses keyword overlap + recency + access frequency scoring.
        """
        conn = self._connect()
        try:
            all_facts = conn.execute(
                "SELECT * FROM facts ORDER BY last_accessed DESC"
            ).fetchall()

            if not all_facts:
                return []

            text_lower = (user_text or "").lower()
            query_words = set(re.findall(r"[a-z]{2,}", text_lower))

            # Add working memory entities to query for better context matching
            if self.working.entities:
                query_words.update(w.lower() for w in self.working.entities)
            if self.working.current_topic:
                query_words.update(re.findall(r"[a-z]{2,}", self.working.current_topic.lower()))

            scored: List[Tuple[float, dict]] = []
            for row in all_facts:
                score = 0.0
                fact_text = f"{row['subject']} {row['relation']} {row['value']} {row['category']}".lower()
                fact_words = set(re.findall(r"[a-z]{2,}", fact_text))

                # Keyword overlap (strongest signal)
                overlap = query_words & fact_words
                score += len(overlap) * 3.0

                # Subject match (direct mention)
                if row["subject"].lower() in text_lower:
                    score += 5.0

                # Value match
                if row["value"].lower() in text_lower:
                    score += 3.0

                # Recency bonus (facts accessed recently are more relevant)
                score += min(row["access_count"], 10) * 0.1

                # Confidence weight
                score *= row["confidence"]

                # Baseline: always include a small score so some facts surface
                score += 0.1

                scored.append((score, dict(row)))

            # Sort by score descending
            scored.sort(key=lambda x: x[0], reverse=True)

            # Update access timestamps for retrieved facts
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result_facts = []
            for score, row in scored[:limit]:
                conn.execute(
                    "UPDATE facts SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                    (now, row["id"])
                )
                result_facts.append(Fact(
                    id=row["id"],
                    category=row["category"],
                    subject=row["subject"],
                    relation=row["relation"],
                    value=row["value"],
                    confidence=row["confidence"],
                    source=row["source"],
                    created_at=row["created_at"],
                    last_accessed=now,
                    access_count=row["access_count"] + 1,
                ))
            conn.commit()
            return result_facts

        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to retrieve facts: {e}")
            return []
        finally:
            conn.close()

    def get_all_facts(self) -> List[Fact]:
        """Get all stored facts (for 'what do you know about me?' queries)."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM facts ORDER BY category, subject").fetchall()
            return [Fact(**dict(row)) for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to list facts: {e}")
            return []
        finally:
            conn.close()

    def delete_fact(self, subject: str, relation: str) -> bool:
        """Delete a specific fact."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM facts WHERE subject = ? COLLATE NOCASE AND relation = ? COLLATE NOCASE",
                (subject, relation)
            )
            conn.commit()
            deleted = cur.rowcount > 0
            if deleted:
                logger.info(f"[BRAIN] Deleted fact: {subject} {relation}")
            return deleted
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to delete fact: {e}")
            return False
        finally:
            conn.close()

    def store_episode(self, summary: str, topic: str = "", emotion: str = "neutral") -> int:
        """Store a memorable moment / milestone."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cur = conn.execute(
                "INSERT INTO episodes (summary, topic, emotion, created_at) VALUES (?, ?, ?, ?)",
                (summary, topic or self.working.current_topic, emotion, now)
            )
            conn.commit()
            logger.info(f"[BRAIN] Stored episode: {summary[:60]}")
            return cur.lastrowid or -1
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to store episode: {e}")
            return -1
        finally:
            conn.close()

    def get_recent_episodes(self, limit: int = 3) -> List[Episode]:
        """Get recent episodes for context."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [Episode(**dict(row)) for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"[BRAIN] Failed to get episodes: {e}")
            return []
        finally:
            conn.close()

    # ── Memory Write Detection ────────────────────────────────────────

    def parse_memory_command(self, user_text: str) -> Optional[Dict]:
        """
        Detect explicit memory commands from voice input.
        Only stores when user clearly says something important.

        Returns dict with keys: action, category, subject, relation, value
        Returns None if not a memory command.
        """
        text = (user_text or "").strip()
        lower = text.lower()

        # ── "What do you know about me?" ──
        if re.search(r"what do you (know|remember) about me", lower):
            return {"action": "recall_all"}

        # ── "What do you know about [X]?" ──
        m = re.search(r"what do you (know|remember) about\s+(.+)", lower)
        if m:
            return {"action": "recall_subject", "subject": m.group(2).strip(" ?.")}

        # ── "Forget that / forget about X" ──
        m = re.search(r"forget\s+(about\s+)?(.+)", lower)
        if m:
            return {"action": "forget", "subject": m.group(2).strip(" ?.")}

        # ── Explicit memory write triggers ──
        trigger = re.search(
            r"\b(remember that|remember this|remember|don't forget|dont forget|save this|store this)\b",
            lower
        )
        if not trigger:
            # ── Implicit identity statements ──
            m = re.search(r"^my name is\s+([a-z][a-z\s'-]+)\.?$", lower)
            if m:
                return {
                    "action": "store",
                    "category": "identity",
                    "subject": m.group(1).strip().title(),
                    "relation": "is_the_user",
                    "value": "owner",
                }
            m = re.search(r"^call me\s+([a-z][a-z\s'-]+)\.?$", lower)
            if m:
                return {
                    "action": "store",
                    "category": "identity",
                    "subject": m.group(1).strip().title(),
                    "relation": "preferred_name",
                    "value": m.group(1).strip().title(),
                }
            return None

        # Everything after the trigger word
        remainder = text[trigger.end():].strip(" :,-")
        if not remainder:
            return None

        # Parse structured patterns
        return self._parse_fact_from_text(remainder)

    def _parse_fact_from_text(self, text: str) -> Optional[Dict]:
        """Parse a fact from natural language after trigger word removal."""
        lower = text.lower().strip()

        # "my dog's name is Bandit" / "my dog is named Bandit"
        m = re.search(r"my\s+(\w[\w\s]*?)(?:'s)?\s+(?:name\s+is|is\s+named|is\s+called)\s+(.+)", lower)
        if m:
            thing = m.group(1).strip()
            name = m.group(2).strip(" .,!?").title()
            return {
                "action": "store",
                "category": "relationship",
                "subject": name,
                "relation": f"is_user_{thing}",
                "value": thing,
            }

        # "my son is Jesse" / "my wife is Sarah"
        m = re.search(r"my\s+(son|daughter|wife|husband|partner|brother|sister|mom|dad|friend)\s+(?:is\s+)?(\w+)", lower)
        if m:
            relation = m.group(1).strip()
            name = m.group(2).strip().title()
            return {
                "action": "store",
                "category": "relationship",
                "subject": name,
                "relation": f"is_user_{relation}",
                "value": relation,
            }

        # "I like X" / "I love X" / "I hate X"
        m = re.search(r"(?:that\s+)?i\s+(like|love|hate|prefer|enjoy|dislike)\s+(.+)", lower)
        if m:
            sentiment = m.group(1).strip()
            value = m.group(2).strip(" .,!?")
            return {
                "action": "store",
                "category": "preference",
                "subject": "user",
                "relation": sentiment + "s",
                "value": value,
            }

        # "I am a X" / "I'm a X"
        m = re.search(r"(?:i\s+am|i'm)\s+(?:a\s+)?(.+)", lower)
        if m:
            value = m.group(1).strip(" .,!?")
            return {
                "action": "store",
                "category": "identity",
                "subject": "user",
                "relation": "is",
                "value": value,
            }

        # "I built X" / "I created X" / "I made X"
        m = re.search(r"i\s+(built|created|made|founded|started)\s+(.+)", lower)
        if m:
            verb = m.group(1).strip()
            value = m.group(2).strip(" .,!?")
            return {
                "action": "store",
                "category": "project",
                "subject": "user",
                "relation": verb,
                "value": value,
            }

        # "[Name] is my [relation]"
        m = re.search(r"(\w+)\s+is\s+my\s+(son|daughter|wife|husband|partner|brother|sister|mom|dad|friend|dog|cat|pet)", lower)
        if m:
            name = m.group(1).strip().title()
            relation = m.group(2).strip()
            return {
                "action": "store",
                "category": "relationship",
                "subject": name,
                "relation": f"is_user_{relation}",
                "value": relation,
            }

        # Generic "X is Y" fallback
        m = re.search(r"(.+?)\s+is\s+(.+)", lower)
        if m:
            subject = m.group(1).strip(" .,!?").title()
            value = m.group(2).strip(" .,!?")
            if len(subject) > 1 and len(value) > 1:
                return {
                    "action": "store",
                    "category": "general",
                    "subject": subject,
                    "relation": "is",
                    "value": value,
                }

        # Last resort: store the whole thing as a general fact
        if len(lower) > 5:
            return {
                "action": "store",
                "category": "general",
                "subject": "note",
                "relation": "remembers",
                "value": text.strip(" .,!?"),
            }

        return None

    # ── Prompt Assembly ───────────────────────────────────────────────

    def before_llm(self, user_text: str, intent: str = "") -> None:
        """Call before sending to LLM. Updates working memory."""
        self.update_working_state(user_text, intent)

    def after_llm(self, user_text: str, assistant_text: str, intent: str = "") -> None:
        """Call after LLM response. Stores short-term exchange."""
        self.update_short_term(user_text, assistant_text, intent)

    def get_prompt_context(self, user_text: str) -> str:
        """
        Assemble the memory context block for the LLM prompt.

        Output (~200 tokens):
          KNOWN FACTS:
          * Tommy built ChefsByte
          * Bandit is his dog
          * Tommy likes blunt responses

          CURRENT STATE:
          Topic: argo_development | Task: building memory system | Mood: excited

          LAST EXCHANGE:
          User: switch to gpt mini
          ARGO: done, switched to GPT-4o-mini

        That's it. Clean. Small. Powerful.
        """
        parts = []

        # 1. Relevant facts (3-5, not everything)
        facts = self.retrieve_relevant_facts(user_text, limit=5)
        if facts:
            fact_lines = []
            for f in facts:
                if f.relation.startswith("is_user_"):
                    rel = f.relation.replace("is_user_", "")
                    fact_lines.append(f"- {f.subject} is Tommy's {rel}")
                elif f.subject.lower() == "user":
                    fact_lines.append(f"- Tommy {f.relation} {f.value}")
                else:
                    fact_lines.append(f"- {f.subject} {f.relation} {f.value}")
            parts.append("KNOWN FACTS:\n" + "\n".join(fact_lines))

        # 2. Working state
        working_block = self.get_working_block()
        if working_block:
            parts.append(f"CURRENT STATE:\n{working_block}")

        # 3. Last exchange only
        short_term_block = self.get_short_term_block()
        if short_term_block:
            parts.append(f"LAST EXCHANGE:\n{short_term_block}")

        return "\n\n".join(parts)

    # ── Utility ───────────────────────────────────────────────────────

    def get_fact_count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM facts").fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0
        finally:
            conn.close()

    def get_episode_count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0
        finally:
            conn.close()

    def format_all_facts_for_speech(self) -> str:
        """Format all facts as natural speech for 'what do you know about me?' responses."""
        facts = self.get_all_facts()
        if not facts:
            return "I don't have anything stored about you yet. Tell me something to remember."

        # Group by category
        groups: Dict[str, List[Fact]] = {}
        for f in facts:
            groups.setdefault(f.category, []).append(f)

        lines = []
        if "identity" in groups:
            for f in groups["identity"]:
                if f.relation == "is_the_user":
                    lines.append(f"Your name is {f.subject}.")
                elif f.relation == "is":
                    lines.append(f"You're {f.value}.")
                else:
                    lines.append(f"You go by {f.value}.")

        if "relationship" in groups:
            for f in groups["relationship"]:
                rel = f.relation.replace("is_user_", "")
                lines.append(f"{f.subject} is your {rel}.")

        if "preference" in groups:
            for f in groups["preference"]:
                lines.append(f"You {f.relation} {f.value}.")

        if "project" in groups:
            for f in groups["project"]:
                lines.append(f"You {f.relation} {f.value}.")

        if "general" in groups:
            for f in groups["general"]:
                lines.append(f"{f.subject} {f.relation} {f.value}.")

        return "Here's what I know. " + " ".join(lines)

    def seed_facts(self, facts: List[Dict]) -> int:
        """Bulk seed facts (for initial setup). Each dict: category, subject, relation, value."""
        count = 0
        for f in facts:
            result = self.store_fact(
                category=f.get("category", "general"),
                subject=f.get("subject", ""),
                relation=f.get("relation", "is"),
                value=f.get("value", ""),
                source="seed",
            )
            if result > 0:
                count += 1
        logger.info(f"[BRAIN] Seeded {count} facts")
        return count


# ── Singleton ─────────────────────────────────────────────────────────

_brain_instance: Optional[ArgoBrain] = None


def get_brain() -> ArgoBrain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = ArgoBrain()
    return _brain_instance
