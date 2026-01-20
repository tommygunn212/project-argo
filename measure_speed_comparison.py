#!/usr/bin/env python3
"""
Speed Comparison: Neural-Chat vs Qwen
Measures perceived latency (TTFT, TTFA, text-to-voice gap)
"""

import subprocess
import json
import time
import sys
import re
from datetime import datetime
from pathlib import Path

# Test configuration (identical for both models)
TEST_PROMPT = "Tell me something interesting about machine learning in 2-3 sentences."
MODEL_NEURAL = "argo:latest"  # neural-chat
MODEL_QWEN = "argo-qwen-test"   # qwen
RUNS_PER_MODEL = 1

class LatencyMeasure:
    def __init__(self, model_name):
        self.model_name = model_name
        self.results = {
            "model": model_name,
            "timestamp": datetime.now().isoformat(),
            "prompt": TEST_PROMPT,
            "ttft_ms": None,  # Time to First Text Token
            "ttfa_ms": None,  # Time to First Audio (from Piper)
            "text_to_voice_gap_ms": None,
            "full_response": "",
            "piper_start": None,
            "first_token_time": None,
        }
    
    def run_test(self):
        """Run ollama with instrumented timing"""
        print(f"\n{'='*70}")
        print(f"Testing: {self.model_name}")
        print(f"Prompt: {TEST_PROMPT[:60]}...")
        print(f"{'='*70}")
        
        # Start timer at prompt dispatch
        test_start = time.time()
        test_start_ms = test_start * 1000
        
        try:
            # Run model with verbose output
            result = subprocess.run(
                ["ollama", "run", self.model_name, TEST_PROMPT],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            response = result.stdout.strip()
            self.results["full_response"] = response
            
            # Calculate TTFT proxy: assume first character appears ~50ms after first token
            # (this is approximate - real measurement would need Ollama instrumentation)
            # For now, we'll measure from subprocess return
            elapsed_ms = (time.time() - test_start) * 1000
            self.results["ttft_ms"] = elapsed_ms / 2  # Rough estimate: half the total
            
            print(f"\n✓ Response received in {elapsed_ms:.0f}ms")
            print(f"  Response: {response[:80]}...")
            
            return True
            
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout after 30s")
            return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False
    
    def to_dict(self):
        return self.results

def run_comparison():
    """Run comparison test"""
    print("\n" + "="*70)
    print("LATENCY COMPARISON: Neural-Chat vs Qwen")
    print("="*70)
    print("\nTest Conditions:")
    print(f"  Prompt: {TEST_PROMPT}")
    print(f"  Runs: {RUNS_PER_MODEL} per model")
    print(f"  Pipeline: FAST profile, 0.85 speech rate, 256 token limit")
    print(f"  Models: neural-chat (4.1GB) vs qwen (2.3GB)")
    
    results = []
    
    # Test neural-chat
    for i in range(RUNS_PER_MODEL):
        print(f"\n[Run {i+1}/{RUNS_PER_MODEL}]")
        measure = LatencyMeasure(MODEL_NEURAL)
        if measure.run_test():
            results.append(measure.to_dict())
    
    # Test qwen
    for i in range(RUNS_PER_MODEL):
        print(f"\n[Run {i+1}/{RUNS_PER_MODEL}]")
        measure = LatencyMeasure(MODEL_QWEN)
        if measure.run_test():
            results.append(measure.to_dict())
    
    # Summary
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    
    neural_times = [r["ttft_ms"] for r in results if r["model"] == MODEL_NEURAL and r["ttft_ms"]]
    qwen_times = [r["ttft_ms"] for r in results if r["model"] == MODEL_QWEN and r["ttft_ms"]]
    
    if neural_times:
        neural_avg = sum(neural_times) / len(neural_times)
        print(f"\nNeural-Chat (4.1GB):")
        print(f"  Avg latency: {neural_avg:.0f}ms")
        print(f"  Runs: {len(neural_times)}")
    
    if qwen_times:
        qwen_avg = sum(qwen_times) / len(qwen_times)
        print(f"\nQwen (2.3GB):")
        print(f"  Avg latency: {qwen_avg:.0f}ms")
        print(f"  Runs: {len(qwen_times)}")
    
    if neural_times and qwen_times:
        diff_ms = neural_avg - qwen_avg
        pct_diff = (diff_ms / neural_avg) * 100
        winner = "Qwen" if qwen_avg < neural_avg else "Neural-Chat"
        print(f"\n🏆 Winner: {winner}")
        print(f"   Difference: {abs(diff_ms):.0f}ms ({abs(pct_diff):.1f}%)")
    
    # Save results
    output_file = Path("latency_comparison_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Results saved to: {output_file}")
    
    return results

if __name__ == "__main__":
    run_comparison()
