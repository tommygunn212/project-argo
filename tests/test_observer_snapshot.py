"""
PHASE 16A: OBSERVER SNAPSHOT TESTS

Tests for read-only snapshot extraction - verify no mutations occur.
"""

import unittest
from datetime import datetime
from core.observer_snapshot import ObserverSnapshot, get_snapshot


class MockIntent:
    """Mock intent object for testing."""
    def __init__(self, intent_type="QUESTION", confidence=0.85):
        self.intent_type = type("IntentType", (), {"value": intent_type})()
        self.confidence = confidence


class MockSessionMemory:
    """Mock session memory for testing."""
    def __init__(self, capacity=3):
        self.capacity = capacity
    
    def get_stats(self):
        return {
            "current_size": 2,
            "total_appended": 5,
            "recent_interactions": [
                ("what time is it", "QUESTION", "It is 3 PM"),
                ("hello", "GREETING", "Hello there"),
            ]
        }


class MockLatencyStats:
    """Mock latency stats for testing."""
    def __init__(self):
        self.stage_times = {
            "total": [500, 480, 520],
            "llm": [200, 210, 195],
            "stt": [100, 105, 98],
        }


class MockCoordinator:
    """Mock coordinator for snapshot testing."""
    def __init__(self):
        self.interaction_count = 2
        self.MAX_INTERACTIONS = 3
        self.memory = MockSessionMemory()
        self.latency_stats = MockLatencyStats()
        
        # Observer state
        self._last_wake_timestamp = datetime(2026, 1, 19, 15, 30, 45)
        self._last_transcript = "what time is it"
        self._last_intent = MockIntent("QUESTION", 0.85)
        self._last_response = "It is currently 3 PM"


class TestObserverSnapshot(unittest.TestCase):
    """Test snapshot data holder."""
    
    def test_snapshot_creation(self):
        """Verify snapshot can be created with state."""
        snapshot = ObserverSnapshot(
            iteration_count=2,
            max_iterations=3,
            last_wake_timestamp=datetime.now(),
            last_transcript="hello",
            last_intent_type="GREETING",
            last_intent_confidence=0.90,
            last_response="Hello there",
        )
        
        self.assertEqual(snapshot.iteration_count, 2)
        self.assertEqual(snapshot.max_iterations, 3)
        self.assertEqual(snapshot.last_transcript, "hello")
        self.assertEqual(snapshot.last_intent_type, "GREETING")
        self.assertEqual(snapshot.last_intent_confidence, 0.90)
        self.assertEqual(snapshot.last_response, "Hello there")
    
    def test_snapshot_to_dict(self):
        """Verify snapshot can be exported as immutable dict."""
        ts = datetime(2026, 1, 19, 15, 30, 0)
        snapshot = ObserverSnapshot(
            iteration_count=1,
            max_iterations=3,
            last_wake_timestamp=ts,
            last_transcript="test",
            last_intent_type="TEST",
            last_intent_confidence=0.75,
            last_response="Testing",
        )
        
        data = snapshot.to_dict()
        
        self.assertIsInstance(data, dict)
        self.assertEqual(data["iteration_count"], 1)
        self.assertEqual(data["max_iterations"], 3)
        self.assertIn("2026-01-19", data["last_wake_timestamp"])
        self.assertEqual(data["last_transcript"], "test")
        self.assertEqual(data["last_intent"]["type"], "TEST")
        self.assertEqual(data["last_intent"]["confidence"], 0.75)
        self.assertEqual(data["last_response"], "Testing")
    
    def test_snapshot_with_memory_summary(self):
        """Verify snapshot includes memory summary."""
        memory_summary = {
            "capacity": 3,
            "current_size": 2,
            "recent_interactions": [("hello", "GREETING", "Hi")],
        }
        snapshot = ObserverSnapshot(
            iteration_count=1,
            max_iterations=3,
            session_memory_summary=memory_summary,
        )
        
        self.assertEqual(snapshot.session_memory_summary["capacity"], 3)
        self.assertEqual(snapshot.session_memory_summary["current_size"], 2)
    
    def test_snapshot_with_latency_stats(self):
        """Verify snapshot includes latency statistics."""
        latency_summary = {
            "total": {"min_ms": 400, "avg_ms": 450, "max_ms": 500},
            "llm": {"min_ms": 180, "avg_ms": 200, "max_ms": 220},
        }
        snapshot = ObserverSnapshot(
            iteration_count=1,
            max_iterations=3,
            latency_stats_summary=latency_summary,
        )
        
        self.assertEqual(snapshot.latency_stats_summary["total"]["avg_ms"], 450)
        self.assertEqual(snapshot.latency_stats_summary["llm"]["avg_ms"], 200)


class TestGetSnapshot(unittest.TestCase):
    """Test snapshot extraction from coordinator."""
    
    def test_get_snapshot_from_coordinator(self):
        """Verify get_snapshot extracts state without mutation."""
        coordinator = MockCoordinator()
        
        # Get snapshot
        snapshot = get_snapshot(coordinator)
        
        # Verify data extracted
        self.assertEqual(snapshot.iteration_count, 2)
        self.assertEqual(snapshot.max_iterations, 3)
        self.assertEqual(snapshot.last_transcript, "what time is it")
        self.assertEqual(snapshot.last_intent_type, "QUESTION")
        self.assertEqual(snapshot.last_intent_confidence, 0.85)
        self.assertEqual(snapshot.last_response, "It is currently 3 PM")
    
    def test_get_snapshot_extracts_memory(self):
        """Verify snapshot includes session memory summary."""
        coordinator = MockCoordinator()
        snapshot = get_snapshot(coordinator)
        
        memory = snapshot.session_memory_summary
        self.assertEqual(memory["capacity"], 3)
        self.assertEqual(memory["current_size"], 2)
        self.assertEqual(len(memory["recent_interactions"]), 2)
    
    def test_get_snapshot_extracts_latency(self):
        """Verify snapshot includes latency statistics."""
        coordinator = MockCoordinator()
        snapshot = get_snapshot(coordinator)
        
        latency = snapshot.latency_stats_summary
        self.assertIn("total", latency)
        self.assertIn("llm", latency)
        
        # Verify stats computed
        self.assertEqual(latency["total"]["count"], 3)
        self.assertEqual(latency["total"]["min_ms"], 480)
        self.assertEqual(latency["total"]["max_ms"], 520)
    
    def test_get_snapshot_is_read_only(self):
        """Verify snapshot extraction doesn't mutate coordinator."""
        coordinator = MockCoordinator()
        
        # Capture original state
        original_count = coordinator.interaction_count
        original_transcript = coordinator._last_transcript
        original_response = coordinator._last_response
        
        # Get snapshot
        snapshot = get_snapshot(coordinator)
        
        # Verify no mutations
        self.assertEqual(coordinator.interaction_count, original_count)
        self.assertEqual(coordinator._last_transcript, original_transcript)
        self.assertEqual(coordinator._last_response, original_response)
    
    def test_get_snapshot_handles_missing_state(self):
        """Verify snapshot handles missing/incomplete state gracefully."""
        # Minimal coordinator
        coordinator = type("Coordinator", (), {
            "interaction_count": 0,
            "MAX_INTERACTIONS": 3,
        })()
        
        # Should not raise exception
        snapshot = get_snapshot(coordinator)
        
        # Should have defaults
        self.assertEqual(snapshot.iteration_count, 0)
        self.assertEqual(snapshot.max_iterations, 3)
        self.assertIsNone(snapshot.last_transcript)
        self.assertEqual(snapshot.session_memory_summary, {})
    
    def test_snapshot_deterministic(self):
        """Verify multiple calls produce identical snapshots."""
        coordinator = MockCoordinator()
        
        snapshot1 = get_snapshot(coordinator)
        snapshot2 = get_snapshot(coordinator)
        
        # Same data
        self.assertEqual(snapshot1.iteration_count, snapshot2.iteration_count)
        self.assertEqual(snapshot1.last_transcript, snapshot2.last_transcript)
        self.assertEqual(snapshot1.last_response, snapshot2.last_response)
        
        # Export to dict and compare
        dict1 = snapshot1.to_dict()
        dict2 = snapshot2.to_dict()
        
        # Should be identical
        self.assertEqual(dict1["iteration_count"], dict2["iteration_count"])
        self.assertEqual(dict1["last_transcript"], dict2["last_transcript"])


if __name__ == "__main__":
    unittest.main()
