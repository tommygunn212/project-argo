"""
TASK 15: Quick Test - Verify Latency Instrumentation

Runs a simple mock coordinator test to verify timing works.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.latency_probe import LatencyProbe, LatencyStats
import time

def test_latency_probe():
    """Test the latency probe works."""
    print("\n" + "="*60)
    print("Testing Latency Probe")
    print("="*60 + "\n")
    
    # Create a probe
    probe = LatencyProbe(1)
    
    # Mark events
    probe.mark("wake_detected")
    time.sleep(0.01)
    probe.mark("recording_start")
    time.sleep(0.05)
    probe.mark("recording_end")
    time.sleep(0.02)
    probe.mark("stt_start")
    time.sleep(0.1)
    probe.mark("stt_end")
    time.sleep(0.01)
    probe.mark("parsing_start")
    time.sleep(0.01)
    probe.mark("parsing_end")
    time.sleep(0.02)
    probe.mark("llm_start")
    time.sleep(0.2)
    probe.mark("llm_end")
    time.sleep(0.01)
    probe.mark("tts_start")
    time.sleep(0.05)
    probe.mark("tts_end")
    
    # Finalize and log
    probe.log_summary()
    
    # Verify durations were computed
    summary = probe.get_summary()
    assert "total" in summary, "Total duration not computed"
    assert summary["total"] > 0, "Total duration should be positive"
    
    print("✅ Probe test passed\n")

def test_latency_stats():
    """Test stats aggregation."""
    print("="*60)
    print("Testing Latency Stats")
    print("="*60 + "\n")
    
    stats = LatencyStats()
    
    # Add multiple probes
    for i in range(3):
        probe = LatencyProbe(i+1)
        
        probe.mark("wake_detected")
        time.sleep(0.01 * (i+1))  # Vary timings
        probe.mark("recording_start")
        time.sleep(0.05)
        probe.mark("recording_end")
        time.sleep(0.02)
        probe.mark("stt_start")
        time.sleep(0.1)
        probe.mark("stt_end")
        time.sleep(0.01)
        probe.mark("parsing_start")
        time.sleep(0.01)
        probe.mark("parsing_end")
        time.sleep(0.02)
        probe.mark("llm_start")
        time.sleep(0.2)
        probe.mark("llm_end")
        time.sleep(0.01)
        probe.mark("tts_start")
        time.sleep(0.05)
        probe.mark("tts_end")
        
        stats.add_probe(probe)
    
    # Print report
    report = stats.print_report()
    print(report)
    
    # Verify stats
    total_stats = stats.get_stats("total")
    assert total_stats is not None, "Total stats should exist"
    assert total_stats["count"] == 3, "Should have 3 measurements"
    assert total_stats["min"] > 0, "Min should be positive"
    assert total_stats["max"] >= total_stats["min"], "Max should be >= min"
    assert total_stats["avg"] >= total_stats["min"], "Avg should be >= min"
    
    print("✅ Stats test passed\n")

if __name__ == "__main__":
    try:
        test_latency_probe()
        test_latency_stats()
        print("="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60 + "\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
