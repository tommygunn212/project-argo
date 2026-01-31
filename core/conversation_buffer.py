"""
RAM-only conversation buffer.

Contract:
- No disk writes.
- Fixed-size ring buffer.
- Used for prompt context only (not facts).
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, List
import logging

logger = logging.getLogger("ARGO.ConversationBuffer")


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str


class ConversationBuffer:
    def __init__(self, max_turns: int = 8):
        self.max_turns = max(1, int(max_turns))
        self._turns: Deque[ConversationTurn] = deque(maxlen=self.max_turns)

    def clear(self) -> None:
        self._turns.clear()

    def add(self, role: str, content: str) -> None:
        if not content:
            return
        ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._turns.append(ConversationTurn(role=role, content=content, timestamp=ts))
        logger.info("[CONVO] Buffer size=%s", len(self._turns))

    def as_context_block(self) -> str:
        if not self._turns:
            return ""
        lines: List[str] = ["Conversation context (RAM-only):"]
        for turn in self._turns:
            lines.append(f"{turn.role}: {turn.content}")
        return "\n".join(lines)

    def size(self) -> int:
        return len(self._turns)
