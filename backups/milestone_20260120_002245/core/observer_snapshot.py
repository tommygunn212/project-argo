"""
PHASE 16A: OBSERVER SNAPSHOT

Pure read-only data extraction from Coordinator state.
No writes. No side effects. No logging.

Exports internal state safely for external observation dashboards.
"""

from typing import Optional, Dict, Any
from datetime import datetime


class ObserverSnapshot:
    """
    Captures a read-only snapshot of current Coordinator state.
    
    Pure data holder - no logic, no mutations.
    """
    
    def __init__(
        self,
        iteration_count: int,
        max_iterations: int,
        last_wake_timestamp: Optional[datetime] = None,
        last_transcript: Optional[str] = None,
        last_intent_type: Optional[str] = None,
        last_intent_confidence: Optional[float] = None,
        last_response: Optional[str] = None,
        session_memory_summary: Optional[Dict[str, Any]] = None,
        latency_stats_summary: Optional[Dict[str, Any]] = None,
    ):
        """Initialize snapshot with read-only state."""
        self.iteration_count = iteration_count
        self.max_iterations = max_iterations
        self.last_wake_timestamp = last_wake_timestamp
        self.last_transcript = last_transcript
        self.last_intent_type = last_intent_type
        self.last_intent_confidence = last_intent_confidence
        self.last_response = last_response
        self.session_memory_summary = session_memory_summary or {}
        self.latency_stats_summary = latency_stats_summary or {}
    
    def to_dict(self) -> dict:
        """Export snapshot as dictionary (immutable representation)."""
        return {
            "iteration_count": self.iteration_count,
            "max_iterations": self.max_iterations,
            "last_wake_timestamp": self.last_wake_timestamp.isoformat() if self.last_wake_timestamp else None,
            "last_transcript": self.last_transcript,
            "last_intent": {
                "type": self.last_intent_type,
                "confidence": self.last_intent_confidence,
            },
            "last_response": self.last_response,
            "session_memory": self.session_memory_summary,
            "latency_stats": self.latency_stats_summary,
        }
    
    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"ObserverSnapshot("
            f"iteration={self.iteration_count}/{self.max_iterations}, "
            f"transcript='{self.last_transcript[:30]}...'" if self.last_transcript else "None"
            f", intent={self.last_intent_type})"
        )


def get_snapshot(coordinator) -> ObserverSnapshot:
    """
    Extract read-only snapshot from Coordinator.
    
    Pure function - reads state, never writes or mutates.
    
    Args:
        coordinator: Coordinator instance (v4 with SessionMemory + latency instrumentation)
    
    Returns:
        ObserverSnapshot with current system state
    
    Raises:
        AttributeError: If coordinator is missing expected attributes
    """
    
    # === ITERATION STATE ===
    iteration_count = coordinator.interaction_count
    max_iterations = coordinator.MAX_INTERACTIONS
    
    # === SESSION MEMORY SUMMARY ===
    # Memory is available via coordinator.memory (SessionMemory instance)
    memory_summary = {}
    if hasattr(coordinator, "memory") and coordinator.memory is not None:
        try:
            # Get memory stats (size, capacity, recent interactions)
            stats = coordinator.memory.get_stats()
            memory_summary = {
                "capacity": coordinator.memory.capacity,
                "current_size": stats["current_size"],
                "total_appended": stats["total_appended"],
                "recent_interactions": [
                    {
                        "utterance": entry[0],
                        "intent": entry[1],
                        "response": entry[2],
                    }
                    for entry in stats.get("recent_interactions", [])
                ],
            }
        except Exception:
            memory_summary = {"status": "memory unavailable"}
    
    # === LATENCY STATS SUMMARY ===
    latency_summary = {}
    if hasattr(coordinator, "latency_stats") and coordinator.latency_stats is not None:
        try:
            # Get latency statistics (aggregated across interactions)
            stages = coordinator.latency_stats.stage_times
            latency_summary = {}
            for stage_name, samples in stages.items():
                if samples:
                    latency_summary[stage_name] = {
                        "count": len(samples),
                        "min_ms": min(samples),
                        "max_ms": max(samples),
                        "avg_ms": sum(samples) / len(samples),
                        "median_ms": sorted(samples)[len(samples) // 2],
                    }
        except Exception:
            latency_summary = {"status": "latency stats unavailable"}
    
    # === LAST INTERACTION DATA ===
    # These come from the most recent on_trigger_detected callback
    # We access them from coordinator state (set during callback)
    
    last_wake_timestamp = None
    if hasattr(coordinator, "_last_wake_timestamp"):
        last_wake_timestamp = coordinator._last_wake_timestamp
    
    last_transcript = None
    if hasattr(coordinator, "_last_transcript"):
        last_transcript = coordinator._last_transcript
    
    last_intent_type = None
    last_intent_confidence = None
    if hasattr(coordinator, "_last_intent"):
        intent = coordinator._last_intent
        if intent:
            last_intent_type = intent.intent_type.value if hasattr(intent, "intent_type") else str(intent)
            last_intent_confidence = intent.confidence if hasattr(intent, "confidence") else None
    
    last_response = None
    if hasattr(coordinator, "_last_response"):
        last_response = coordinator._last_response
    
    # === CREATE SNAPSHOT ===
    return ObserverSnapshot(
        iteration_count=iteration_count,
        max_iterations=max_iterations,
        last_wake_timestamp=last_wake_timestamp,
        last_transcript=last_transcript,
        last_intent_type=last_intent_type,
        last_intent_confidence=last_intent_confidence,
        last_response=last_response,
        session_memory_summary=memory_summary,
        latency_stats_summary=latency_summary,
    )
