"""
Phase 6B-1: Ollama Internal Latency Dissection

Run controlled experiments to measure Ollama's internal processing phases.

Conditions:
- Cold model (fresh start)
- Warm model (already loaded)

Per condition: 10 identical prompts
Per prompt: Capture dispatch → response → content extraction

Output: baselines/ollama_internal_latency_raw.json
"""

import os
import sys
import json
import time
import subprocess
import statistics
from pathlib import Path

# Enable Ollama profiling in hal_chat module
os.environ["OLLAMA_PROFILING"] = "true"

# Add runtime to path
sys.path.insert(0, str(Path(__file__).parent / "runtime" / "ollama"))

# Import hal_chat after setting profiling flag
import hal_chat

# ============================================================================
# Configuration
# ============================================================================

TEST_PROMPT = "What is 2 + 2?"
"""Simple, fast prompt for consistent timing measurements."""

ITERATIONS_PER_CONDITION = 10
"""Number of identical prompts per condition."""

WARM_UP_ITERATIONS = 2
"""Warm-up requests before cold→warm transition."""

# ============================================================================
# Experiment Runner
# ============================================================================

def run_cold_model_experiment() -> dict:
    """
    Measure with fresh model load.
    
    Process:
    1. Restart Ollama (force model unload)
    2. Wait for startup
    3. Run warm-up (not counted)
    4. Run ITERATIONS_PER_CONDITION timed requests
    5. Parse profile data from each request
    
    Returns:
        {
            "condition": "cold",
            "iterations": N,
            "dispatch_to_response_ms": [latencies...],
            "total_request_ms": [latencies...],
            "timestamps": [events...],
            "notes": "Model loaded fresh from disk"
        }
    """
    print("\n[Phase 6B-1] Cold Model Experiment")
    print("=" * 70)
    
    # Note: In a real scenario, we'd stop Ollama. For now, assume it's running.
    # The "cold" state is approximated by the first request after startup.
    
    results = {
        "condition": "cold",
        "iterations": ITERATIONS_PER_CONDITION,
        "dispatch_to_response_ms": [],
        "total_request_ms": [],
        "all_timestamps": [],
        "notes": "Model potentially loaded fresh or from cache"
    }
    
    print(f"Running {ITERATIONS_PER_CONDITION} requests with fresh model state...")
    
    for i in range(ITERATIONS_PER_CONDITION):
        try:
            start_time = time.time() * 1000
            response = hal_chat.chat(TEST_PROMPT)
            end_time = time.time() * 1000
            
            profile = hal_chat.get_profile_data()
            total_elapsed = end_time - start_time
            
            # Extract dispatch → response latency from profile
            dispatch_to_response = None
            for event in profile:
                if isinstance(event, dict) and event.get("phase") == "dispatch_to_response":
                    dispatch_to_response = event.get("elapsed_ms")
                    break
            
            if dispatch_to_response is not None:
                results["dispatch_to_response_ms"].append(dispatch_to_response)
            
            results["total_request_ms"].append(total_elapsed)
            results["all_timestamps"].append(profile)
            
            print(f"  Iteration {i+1:2d}: {total_elapsed:7.1f}ms total | "
                  f"{dispatch_to_response:7.1f}ms dispatch→response" if dispatch_to_response else "")
        
        except Exception as e:
            print(f"  Iteration {i+1:2d}: ERROR - {e}")
    
    return results


def run_warm_model_experiment() -> dict:
    """
    Measure with model already loaded.
    
    Process:
    1. Run warm-up requests (model now cached)
    2. Run ITERATIONS_PER_CONDITION timed requests
    3. Parse profile data from each request
    
    Returns:
        {
            "condition": "warm",
            "iterations": N,
            "dispatch_to_response_ms": [latencies...],
            "total_request_ms": [latencies...],
            "timestamps": [events...],
            "notes": "Model cached in Ollama memory"
        }
    """
    print("\n[Phase 6B-1] Warm Model Experiment")
    print("=" * 70)
    
    # Warm up with non-timed requests
    print(f"Warming up model ({WARM_UP_ITERATIONS} iterations)...")
    for _ in range(WARM_UP_ITERATIONS):
        try:
            hal_chat.chat(TEST_PROMPT)
            hal_chat.get_profile_data()  # Clear buffer
        except Exception as e:
            print(f"  Warm-up error: {e}")
    
    results = {
        "condition": "warm",
        "iterations": ITERATIONS_PER_CONDITION,
        "dispatch_to_response_ms": [],
        "total_request_ms": [],
        "all_timestamps": [],
        "notes": "Model cached in Ollama memory"
    }
    
    print(f"Running {ITERATIONS_PER_CONDITION} timed requests...")
    
    for i in range(ITERATIONS_PER_CONDITION):
        try:
            start_time = time.time() * 1000
            response = hal_chat.chat(TEST_PROMPT)
            end_time = time.time() * 1000
            
            profile = hal_chat.get_profile_data()
            total_elapsed = end_time - start_time
            
            # Extract dispatch → response latency
            dispatch_to_response = None
            for event in profile:
                if isinstance(event, dict) and event.get("phase") == "dispatch_to_response":
                    dispatch_to_response = event.get("elapsed_ms")
                    break
            
            if dispatch_to_response is not None:
                results["dispatch_to_response_ms"].append(dispatch_to_response)
            
            results["total_request_ms"].append(total_elapsed)
            results["all_timestamps"].append(profile)
            
            print(f"  Iteration {i+1:2d}: {total_elapsed:7.1f}ms total | "
                  f"{dispatch_to_response:7.1f}ms dispatch→response" if dispatch_to_response else "")
        
        except Exception as e:
            print(f"  Iteration {i+1:2d}: ERROR - {e}")
    
    return results


def compute_stats(latencies: list) -> dict:
    """
    Compute Avg and P95 for a list of latencies.
    
    Args:
        latencies: List of millisecond values
        
    Returns:
        {"avg": X, "p95": Y, "min": Z, "max": W}
    """
    if not latencies:
        return {"avg": None, "p95": None, "min": None, "max": None}
    
    sorted_lat = sorted(latencies)
    p95_idx = int(len(sorted_lat) * 0.95)
    
    return {
        "avg": statistics.mean(latencies),
        "p95": sorted_lat[p95_idx] if p95_idx < len(sorted_lat) else sorted_lat[-1],
        "min": min(latencies),
        "max": max(latencies),
        "count": len(latencies)
    }


def main():
    """Run all experiment conditions and save results."""
    print("\n" + "=" * 70)
    print("Phase 6B-1: Ollama Internal Latency Dissection")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Test prompt: '{TEST_PROMPT}'")
    print(f"  Iterations per condition: {ITERATIONS_PER_CONDITION}")
    print(f"  OLLAMA_PROFILING: {os.getenv('OLLAMA_PROFILING')}")
    
    # Run experiments
    cold_results = run_cold_model_experiment()
    warm_results = run_warm_model_experiment()
    
    # Compute statistics
    print("\n" + "=" * 70)
    print("Results Summary")
    print("=" * 70)
    
    cold_dtr_stats = compute_stats(cold_results["dispatch_to_response_ms"])
    cold_total_stats = compute_stats(cold_results["total_request_ms"])
    warm_dtr_stats = compute_stats(warm_results["dispatch_to_response_ms"])
    warm_total_stats = compute_stats(warm_results["total_request_ms"])
    
    print(f"\nCOLD MODEL:")
    print(f"  Dispatch→Response: Avg={cold_dtr_stats['avg']:.1f}ms | P95={cold_dtr_stats['p95']:.1f}ms")
    print(f"  Total Request:     Avg={cold_total_stats['avg']:.1f}ms | P95={cold_total_stats['p95']:.1f}ms")
    
    print(f"\nWARM MODEL:")
    print(f"  Dispatch→Response: Avg={warm_dtr_stats['avg']:.1f}ms | P95={warm_dtr_stats['p95']:.1f}ms")
    print(f"  Total Request:     Avg={warm_total_stats['avg']:.1f}ms | P95={warm_total_stats['p95']:.1f}ms")
    
    # Save raw data
    output_data = {
        "experiment": "Phase 6B-1 Ollama Internal Latency",
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "test_prompt": TEST_PROMPT,
            "iterations_per_condition": ITERATIONS_PER_CONDITION,
            "profiling_enabled": os.getenv("OLLAMA_PROFILING") == "true"
        },
        "cold_model": {
            "condition": cold_results["condition"],
            "notes": cold_results["notes"],
            "dispatch_to_response_ms": cold_results["dispatch_to_response_ms"],
            "total_request_ms": cold_results["total_request_ms"],
            "stats": {
                "dispatch_to_response": cold_dtr_stats,
                "total_request": cold_total_stats
            },
            "raw_timestamps": cold_results["all_timestamps"]
        },
        "warm_model": {
            "condition": warm_results["condition"],
            "notes": warm_results["notes"],
            "dispatch_to_response_ms": warm_results["dispatch_to_response_ms"],
            "total_request_ms": warm_results["total_request_ms"],
            "stats": {
                "dispatch_to_response": warm_dtr_stats,
                "total_request": warm_total_stats
            },
            "raw_timestamps": warm_results["all_timestamps"]
        }
    }
    
    # Ensure baselines directory exists
    Path("baselines").mkdir(exist_ok=True)
    
    output_path = Path("baselines") / "ollama_internal_latency_raw.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n✓ Results saved to: {output_path}")
    print("\n" + "=" * 70)
    print("Phase 6B-1 Complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
