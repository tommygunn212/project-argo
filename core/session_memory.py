"""
Session Memory: Short-term working memory for a single session.

This memory is:
- SHORT-TERM: Cleared when program exits
- EXPLICIT: Visible in code, no magic
- BOUNDED: Fixed size, auto-evicting
- NOT LEARNING: No embeddings, no summarization, no personality

This is a scratchpad for recent interactions only.
"""

from collections import deque
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class InteractionRecord:
    """Single interaction: utterance → intent → response."""
    timestamp: datetime
    user_utterance: str
    parsed_intent: str
    generated_response: str


class SessionMemory:
    """
    Bounded ring buffer for session interactions.
    
    Stores:
    - Last N user utterances
    - Last N intents
    - Last N responses
    
    Automatically evicts oldest when capacity exceeded.
    """
    
    DEFAULT_CAPACITY = 3  # Store last 3 interactions
    
    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        """
        Initialize session memory.
        
        Args:
            capacity: Max interactions to store (default 3)
        """
        if capacity < 1:
            raise ValueError("Capacity must be >= 1")
        
        self.capacity = capacity
        self.interactions: deque = deque(maxlen=capacity)
        self.created_at = datetime.now()
    
    def append(
        self,
        user_utterance: str,
        parsed_intent: str,
        generated_response: str
    ) -> None:
        """
        Add interaction to memory.
        
        Args:
            user_utterance: What the user said
            parsed_intent: Intent classification (GREETING, QUESTION, etc.)
            generated_response: System response generated
            
        When memory is full, oldest entry is automatically evicted.
        """
        record = InteractionRecord(
            timestamp=datetime.now(),
            user_utterance=user_utterance,
            parsed_intent=parsed_intent,
            generated_response=generated_response
        )
        self.interactions.append(record)
    
    def get_recent_count(self) -> int:
        """Get number of stored interactions."""
        return len(self.interactions)
    
    def is_empty(self) -> bool:
        """Check if memory is empty."""
        return len(self.interactions) == 0
    
    def is_full(self) -> bool:
        """Check if memory is at capacity."""
        return len(self.interactions) == self.capacity
    
    def get_all_interactions(self) -> List[InteractionRecord]:
        """Get all stored interactions (oldest to newest)."""
        return list(self.interactions)
    
    def get_recent_utterances(self, n: Optional[int] = None) -> List[str]:
        """
        Get recent user utterances (newest first).
        
        Args:
            n: How many to return (default all)
            
        Returns:
            List of recent utterances in reverse chronological order
        """
        interactions = list(self.interactions)
        if n is not None:
            interactions = interactions[-n:]
        return [r.user_utterance for r in reversed(interactions)]
    
    def get_recent_intents(self, n: Optional[int] = None) -> List[str]:
        """
        Get recent parsed intents (newest first).
        
        Args:
            n: How many to return (default all)
            
        Returns:
            List of recent intents in reverse chronological order
        """
        interactions = list(self.interactions)
        if n is not None:
            interactions = interactions[-n:]
        return [r.parsed_intent for r in reversed(interactions)]
    
    def get_recent_responses(self, n: Optional[int] = None) -> List[str]:
        """
        Get recent responses (newest first).
        
        Args:
            n: How many to return (default all)
            
        Returns:
            List of recent responses in reverse chronological order
        """
        interactions = list(self.interactions)
        if n is not None:
            interactions = interactions[-n:]
        return [r.generated_response for r in reversed(interactions)]
    
    def get_context_summary(self) -> str:
        """
        Get human-readable summary of recent interactions.
        
        Used by ResponseGenerator to reference context in prompts.
        Format: "You earlier asked X (classified as QUESTION) and I responded Y"
        """
        if self.is_empty():
            return ""
        
        interactions = list(self.interactions)
        summary_parts = []
        
        for i, record in enumerate(reversed(interactions), start=1):
            part = (
                f"Turn {len(interactions) - i + 1}: "
                f"You said '{record.user_utterance}' "
                f"(classified as {record.parsed_intent}). "
                f"I responded '{record.generated_response}'."
            )
            summary_parts.append(part)
        
        return " ".join(summary_parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get memory statistics.
        
        Returns dict with:
        - capacity: Max interactions
        - count: Current interactions
        - full: Whether at capacity
        - session_age_seconds: Time since session started
        """
        session_age = (datetime.now() - self.created_at).total_seconds()
        
        return {
            "capacity": self.capacity,
            "count": len(self.interactions),
            "full": self.is_full(),
            "empty": self.is_empty(),
            "session_age_seconds": round(session_age, 2)
        }
    
    def clear(self) -> None:
        """
        Clear all memory.
        
        Called when starting new session or on shutdown.
        """
        self.interactions.clear()
        self.created_at = datetime.now()
    
    def __str__(self) -> str:
        """String representation for debugging."""
        stats = self.get_stats()
        return (
            f"SessionMemory(capacity={stats['capacity']}, "
            f"count={stats['count']}, "
            f"full={stats['full']})"
        )
    
    def __repr__(self) -> str:
        """Repr for debugging."""
        return self.__str__()
