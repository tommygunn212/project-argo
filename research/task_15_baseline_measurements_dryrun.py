"""
TASK 15 PART B: BASELINE MEASUREMENTS (DRY RUN - SIMULATED)

This is a test version that simulates baseline collection WITHOUT requiring:
- Microphone input
- Speaker output
- Porcupine wake word detection
- Audio capture/playback

It generates synthetic latency data matching expected patterns from real runs
and saves to latency_baseline_measurements.json to verify the collection pipeline works.

Use this to verify the measurement flow before running the real version.
"""

import sys
import logging
import json
import os
from datetime import datetime
import random
import time

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def simulate_baseline_collection():
    """Simulate baseline collection with synthetic data."""
    
    print("=" * 80)
    print("TASK 15 PART B: BASELINE MEASUREMENTS COLLECTION (DRY RUN - SIMULATED)")
    print("=" * 80)
    print()
    print("This simulates the baseline measurement collection WITHOUT audio.")
    print("It generates synthetic latency data to verify the pipeline works.")
    print()
    print("Target: 15 simulated interactions across 5 sessions")
    print()
    
    # Expected latency ranges (ms) from Whisper/Ollama/Edge-TTS
    stage_ranges = {
        "wake_to_record": (8, 15),          # Quick
        "recording": (48, 52),               # ~500ms audio at 16kHz
        "stt": (95, 110),                    # Whisper inference
        "parsing": (8, 12),                  # Rule parsing (fast)
        "llm": (180, 250),                   # Ollama LLM generation
        "tts": (45, 60),                     # Edge-TTS synthesis
    }
    
    all_data = {
        "timestamp": datetime.now().isoformat(),
        "total_interactions": 0,
        "num_sessions": 5,
        "stages": {}
    }
    
    # Initialize stage data
    for stage in stage_ranges:
        all_data["stages"][stage] = {
            "count": 0,
            "samples": [],
            "min_ms": float('inf'),
            "max_ms": float('-inf'),
            "avg_ms": 0.0,
            "median_ms": 0.0
        }
    
    # Simulate 5 sessions × 3 interactions = 15 total
    print("[*] Simulating 5 sessions × 3 interactions = 15 total interactions")
    print()
    
    num_sessions = 5
    interactions_per_session = 3
    
    for session_num in range(1, num_sessions + 1):
        print(f"[*] Simulating Session {session_num}/{num_sessions}...")
        
        for interaction in range(1, interactions_per_session + 1):
            # Generate synthetic latency data
            latencies = {}
            total_ms = 0
            
            for stage, (min_val, max_val) in stage_ranges.items():
                # Add some natural variance
                latency = random.uniform(min_val, max_val)
                latencies[stage] = latency
                total_ms += latency
                
                # Track for aggregation
                all_data["stages"][stage]["samples"].append(latency)
            
            # Add total duration
            latencies["total"] = total_ms
            all_data["stages"]["total"] = all_data["stages"].get("total", {
                "count": 0,
                "samples": [],
                "min_ms": float('inf'),
                "max_ms": float('-inf'),
                "avg_ms": 0.0,
                "median_ms": 0.0
            })
            all_data["stages"]["total"]["samples"].append(total_ms)
            
            all_data["total_interactions"] += 1
            
            # Simulate interaction time
            time.sleep(0.1)  # Brief pause
            print(f"  [{interaction}/{interactions_per_session}] Simulated interaction - {total_ms:.1f}ms total")
        
        print()
    
    # Compute statistics
    print("[*] Computing statistics...")
    print()
    
    for stage in all_data["stages"]:
        samples = all_data["stages"][stage]["samples"]
        if samples:
            all_data["stages"][stage]["count"] = len(samples)
            all_data["stages"][stage]["min_ms"] = min(samples)
            all_data["stages"][stage]["max_ms"] = max(samples)
            all_data["stages"][stage]["avg_ms"] = sum(samples) / len(samples)
            all_data["stages"][stage]["median_ms"] = sorted(samples)[len(samples) // 2]
    
    # Save to JSON
    output_file = "latency_baseline_measurements.json"
    with open(output_file, "w") as f:
        json.dump(all_data, f, indent=2)
    
    print()
    print("=" * 80)
    print("SIMULATED BASELINE RESULTS")
    print("=" * 80)
    print()
    print(f"Total interactions: {all_data['total_interactions']}")
    print()
    print("Stage Latencies:")
    print("-" * 80)
    print(f"{'Stage':<20} {'Count':>6} {'Min(ms)':>10} {'Avg(ms)':>10} {'Max(ms)':>10} {'Median(ms)':>12}")
    print("-" * 80)
    
    for stage in sorted(all_data["stages"].keys()):
        stage_data = all_data["stages"][stage]
        print(
            f"{stage:<20} {stage_data['count']:>6} "
            f"{stage_data['min_ms']:>10.2f} {stage_data['avg_ms']:>10.2f} "
            f"{stage_data['max_ms']:>10.2f} {stage_data['median_ms']:>12.2f}"
        )
    
    print()
    print("=" * 80)
    print(f"[OK] Simulated baseline measurements saved to: {output_file}")
    print("=" * 80)
    print()
    print("Review the generated JSON and verify:")
    print("1. All stages have 15 samples (one per interaction)")
    print("2. Latencies are within expected ranges")
    print("3. LLM stage is slowest (~200ms avg)")
    print("4. Recording stage is consistent (~50ms)")
    print()


if __name__ == "__main__":
    simulate_baseline_collection()
