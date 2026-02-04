"""
RAM-only conversation buffer.

Contract:
- No disk writes.
- Fixed-size ring buffer.
- Used for prompt context only (not facts).

Phase 5 Constraints:
- Max turns for session continuity (configurable via config.json)
- Cleared on STOP, error, command execution
- Toggle support (enabled/disabled)
- Never affects intent classification
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, List, Optional
import logging
import json
from pathlib import Path

logger = logging.getLogger("ARGO.ConversationBuffer")


def _load_session_turn_limit() -> int:
    """Load session turn limit from config.json, default to 6."""
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
                return config.get("session", {}).get("turn_limit", 6)
    except Exception:
        pass
    return 6


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str


class ConversationBuffer:
    """
    Phase 5: Bounded session continuity.
    
    This is NOT memory. This is ephemeral context for follow-up questions.
    Cleared on: restart, STOP, error, command execution.
    """
    
    # Session turn limit - loaded from config.json
    SESSION_TURN_LIMIT = _load_session_turn_limit()
    
    def __init__(self, max_turns: int = 8, enabled: bool = True):
        self.max_turns = max(1, int(max_turns))
        self._turns: Deque[ConversationTurn] = deque(maxlen=self.max_turns)
        self._enabled = enabled
        self._session_turn_count = 0  # Counts conversation exchanges, not buffer size

    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        if not value and self._enabled:
            # Turning off - clear context
            self.clear(reason="toggle OFF")
        self._enabled = value

    def clear(self, reason: str = "unspecified") -> None:
        """Clear buffer with logged reason."""
        if self._turns:
            logger.info(f"[SESSION] Context cleared: {reason}")
        self._turns.clear()
        self._session_turn_count = 0

    def add(self, role: str, content: str) -> None:
        """Add a turn. Respects enabled state and turn limit."""
        if not content:
            return
        if not self._enabled:
            logger.debug("[SESSION] Context disabled, skipping add")
            return
        
        # Track session turns (user+assistant = 1 exchange)
        if role.lower() in ("user", "assistant", "argo"):
            if role.lower() == "user":
                self._session_turn_count += 1
        
        # Check turn limit
        if self._session_turn_count > self.SESSION_TURN_LIMIT:
            self.clear(reason=f"turn limit ({self.SESSION_TURN_LIMIT}) exceeded")
            # Still add this turn as start of new session
            self._session_turn_count = 1
        
        ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._turns.append(ConversationTurn(role=role, content=content, timestamp=ts))
        logger.info(f"[SESSION] Context appended (turn {self._session_turn_count}/{self.SESSION_TURN_LIMIT})")

    def as_context_block(self) -> str:
        """Get context for LLM prompt. Returns empty if disabled."""
        if not self._enabled:
            return ""
        if not self._turns:
            return ""
        # Output verbatim turns - no header, no compression
        lines: List[str] = []
        for turn in self._turns:
            lines.append(f"{turn.role}: {turn.content}")
        return "\n".join(lines)

    def size(self) -> int:
        return len(self._turns)
    
    def session_turn_count(self) -> int:
        """Current session turn count (for Phase 5 monitoring)."""
        return self._session_turn_count
