"""
PHASE 16B: OBSERVER CLI

Human-readable text display of coordinator state.
Read-only visibility dashboard - no controls, no mutations.

Runs once, prints snapshot, exits. No loops.
"""

import sys
import json
from datetime import datetime


def format_timestamp(ts: datetime) -> str:
    """Format timestamp for display."""
    if not ts:
        return "N/A"
    return ts.strftime("%H:%M:%S")


def format_duration(ms: float) -> str:
    """Format duration in milliseconds."""
    if ms is None:
        return "N/A"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms/1000:.2f}s"


def display_snapshot(snapshot):
    """
    Display snapshot in human-readable format.
    
    Args:
        snapshot: ObserverSnapshot instance
    """
    
    print()
    print("=" * 80)
    print(" " * 20 + "ARGO OBSERVER (READ-ONLY DASHBOARD)")
    print("=" * 80)
    print()
    
    # === ITERATION STATE ===
    print("ITERATION STATE")
    print("-" * 80)
    print(f"  Current:  {snapshot.iteration_count}")
    print(f"  Maximum:  {snapshot.max_iterations}")
    percent = (snapshot.iteration_count / snapshot.max_iterations * 100) if snapshot.max_iterations > 0 else 0
    print(f"  Progress: {percent:.0f}%")
    print()
    
    # === LAST INTERACTION ===
    print("LAST INTERACTION")
    print("-" * 80)
    
    if snapshot.last_wake_timestamp:
        print(f"  Wake Time:    {format_timestamp(snapshot.last_wake_timestamp)}")
    else:
        print(f"  Wake Time:    (none)")
    
    if snapshot.last_transcript:
        transcript_display = (
            snapshot.last_transcript[:60] + "..."
            if len(snapshot.last_transcript) > 60
            else snapshot.last_transcript
        )
        print(f"  Transcript:   \"{transcript_display}\"")
    else:
        print(f"  Transcript:   (none)")
    
    if snapshot.last_intent_type:
        confidence_pct = (
            f"{snapshot.last_intent_confidence * 100:.0f}%"
            if snapshot.last_intent_confidence is not None
            else "N/A"
        )
        print(f"  Intent:       {snapshot.last_intent_type} ({confidence_pct})")
    else:
        print(f"  Intent:       (none)")
    
    if snapshot.last_response:
        response_display = (
            snapshot.last_response[:60] + "..."
            if len(snapshot.last_response) > 60
            else snapshot.last_response
        )
        print(f"  Response:     \"{response_display}\"")
    else:
        print(f"  Response:     (none)")
    
    print()
    
    # === SESSION MEMORY ===
    print("SESSION MEMORY")
    print("-" * 80)
    
    memory = snapshot.session_memory_summary
    if memory and memory.get("capacity") is not None:
        capacity = memory.get("capacity", 0)
        current_size = memory.get("current_size", 0)
        print(f"  Capacity:     {current_size} / {capacity} slots used")
        print(f"  Total added:  {memory.get('total_appended', 0)}")
        
        recent = memory.get("recent_interactions", [])
        if recent:
            print(f"  Recent:       {len(recent)} interaction(s)")
            for i, (utterance, intent, response) in enumerate(recent, 1):
                utterance_display = utterance[:40] + "..." if len(utterance) > 40 else utterance
                response_display = response[:40] + "..." if len(response) > 40 else response
                print(f"    [{i}] \"{utterance_display}\" -> \"{response_display}\"")
        else:
            print(f"  Recent:       (empty)")
    else:
        print(f"  Status:       (unavailable)")
    
    print()
    
    # === LATENCY STATISTICS ===
    print("LATENCY STATISTICS")
    print("-" * 80)
    
    latency = snapshot.latency_stats_summary
    if latency and latency.get("total"):
        total_stats = latency["total"]
        print(f"  Total Time:   {format_duration(total_stats.get('avg_ms', 0))} avg")
        print(f"  Range:        {format_duration(total_stats.get('min_ms', 0))} to {format_duration(total_stats.get('max_ms', 0))}")
        print(f"  Samples:      {total_stats.get('count', 0)}")
        
        # Show breakdown of stages
        print()
        print("  Stage Breakdown:")
        stages_to_show = ["llm", "stt", "tts", "recording", "parsing", "wake_to_record"]
        for stage_name in stages_to_show:
            if stage_name in latency:
                stage_data = latency[stage_name]
                avg_ms = stage_data.get("avg_ms", 0)
                total_avg = total_stats.get("avg_ms", 1)
                percent = (avg_ms / total_avg * 100) if total_avg > 0 else 0
                print(f"    {stage_name:<15} {format_duration(avg_ms):>8}  ({percent:>5.1f}%)")
    else:
        print(f"  Status:       (no measurements yet)")
    
    print()
    
    # === FOOTER ===
    print("=" * 80)
    print(" " * 15 + "[LOCK] READ-ONLY OBSERVER (No controls, no state mutation)")
    print("=" * 80)
    print()


def main():
    """
    Main entry point - display observer snapshot and exit.
    
    Usage: python run_observer_cli.py <coordinator_type>
    
    Without arguments, creates a mock coordinator for demonstration.
    """
    
    # Try to import a real coordinator if available
    try:
        # First, try to import from active coordinator module
        # This allows the CLI to be run during/after coordinator execution
        from core.observer_snapshot import get_snapshot
        
        # Check if there's a way to get the current coordinator instance
        # For now, we'll create a mock for demo purposes
        from test_observer_snapshot import MockCoordinator
        
        coordinator = MockCoordinator()
        snapshot = get_snapshot(coordinator)
        
    except Exception as e:
        print(f"[Error] Could not load coordinator: {e}")
        print("[Info] Showing mock snapshot for demonstration")
        
        # Create mock snapshot for demonstration
        from core.observer_snapshot import ObserverSnapshot
        
        snapshot = ObserverSnapshot(
            iteration_count=2,
            max_iterations=3,
            last_wake_timestamp=datetime.now(),
            last_transcript="what is the time",
            last_intent_type="QUESTION",
            last_intent_confidence=0.87,
            last_response="It is currently 15:30 UTC",
            session_memory_summary={
                "capacity": 3,
                "current_size": 2,
                "total_appended": 5,
                "recent_interactions": [
                    ("what time is it", "QUESTION", "It is 3 PM"),
                    ("hello", "GREETING", "Hello there"),
                ]
            },
            latency_stats_summary={
                "total": {"count": 15, "min_ms": 411, "avg_ms": 438, "max_ms": 476},
                "llm": {"count": 15, "min_ms": 181, "avg_ms": 211, "max_ms": 242},
                "stt": {"count": 15, "min_ms": 96, "avg_ms": 102, "max_ms": 110},
                "tts": {"count": 15, "min_ms": 45, "avg_ms": 53, "max_ms": 60},
                "recording": {"count": 15, "min_ms": 49, "avg_ms": 50, "max_ms": 52},
                "parsing": {"count": 15, "min_ms": 9, "avg_ms": 10, "max_ms": 12},
                "wake_to_record": {"count": 15, "min_ms": 9, "avg_ms": 12, "max_ms": 14},
            }
        )
    
    # Display snapshot
    display_snapshot(snapshot)
    
    # Exit cleanly (no loop, no persistence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
