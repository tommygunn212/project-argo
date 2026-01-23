#!/usr/bin/env python3
"""
Comprehensive Speed Comparison Report
Tests all available Ollama models for latency and quality
"""

import subprocess
import json
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Test configuration (identical for all models)
TEST_PROMPT = "Tell me something interesting about machine learning in 2-3 sentences."
DEFAULT_TIMEOUT_SECONDS = 60
MODEL_TIMEOUTS = {
    "qwen3:latest": 120,
}
EXPECTED_TIMEOUT_MODELS = {"qwen3:latest"}

# Models to test (from your current Ollama list)
MODELS_TO_TEST = [
    # Current winner
    ("argo:latest", "Qwen (2.3GB) - CURRENT"),
    ("qwen3:latest", "Qwen 3 - LATEST"),
    
    # Fast alternatives
    ("starling-lm:latest", "Starling LM (4.1GB)"),
    ("neural-chat:latest", "Neural Chat (4.1GB)"),
    ("openhermes:latest", "OpenHermes (4.1GB)"),
    ("mistral:latest", "Mistral (4.4GB)"),
    ("mistral-nemo:latest", "Mistral Nemo (7.1GB)"),
    
    # Other options
    ("llama3.2:latest", "Llama 3.2 (2.0GB)"),
    ("llama3.1:8b", "Llama 3.1:8b (4.9GB)"),
    ("gemma3:1b", "Gemma 3:1b (815MB) - SMALLEST"),
    ("gemma3:latest", "Gemma 3 (3.3GB)"),
]

class ComprehensiveTest:
    def __init__(self):
        self.results = []
        self.timestamp = datetime.now().isoformat()
    
    def test_model(self, model_id, model_name):
        """Test single model"""
        print(f"\n{'─'*70}")
        print(f"Testing: {model_name}")
        print(f"Model ID: {model_id}")
        print(f"{'─'*70}")
        
        test_start = time.time()
        test_start_ms = test_start * 1000
        
        try:
            # Run with timeout
            timeout_seconds = MODEL_TIMEOUTS.get(model_id, DEFAULT_TIMEOUT_SECONDS)
            result = subprocess.run(
                ["ollama", "run", model_id, TEST_PROMPT],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                encoding='utf-8',
                errors='ignore'  # Ignore encoding errors
            )
            
            elapsed_ms = (time.time() - test_start) * 1000
            response = result.stdout.strip()[:100]  # First 100 chars
            
            record = {
                "model_id": model_id,
                "model_name": model_name,
                "latency_ms": elapsed_ms,
                "response_preview": response,
                "success": True,
            }
            
            print(f"✓ Success in {elapsed_ms:.0f}ms")
            print(f"  Response: {response}...")
            
            return record
            
        except subprocess.TimeoutExpired:
            expected_timeout = model_id in EXPECTED_TIMEOUT_MODELS
            timeout_note = "expected" if expected_timeout else "unexpected"
            print(f"✗ Timeout (>{timeout_seconds}s, {timeout_note})")
            return {
                "model_id": model_id,
                "model_name": model_name,
                "latency_ms": timeout_seconds * 1000,
                "response_preview": "TIMEOUT",
                "success": False,
                "expected_timeout": expected_timeout,
            }
        except Exception as e:
            print(f"✗ Error: {type(e).__name__}")
            return {
                "model_id": model_id,
                "model_name": model_name,
                "latency_ms": None,
                "response_preview": str(e)[:50],
                "success": False,
            }
    
    def run_all_tests(self):
        """Test all models"""
        print("\n" + "="*70)
        print("ARGO SPEED COMPARISON: COMPREHENSIVE MODEL TEST")
        print("="*70)
        print(f"\nPrompt: {TEST_PROMPT}")
        print(f"Test Time: {self.timestamp}")
        print(f"Pipeline: FAST profile, 0.85 speech rate, 256 token limit")
        print(f"Total Models: {len(MODELS_TO_TEST)}")
        
        for model_id, model_name in MODELS_TO_TEST:
            result = self.test_model(model_id, model_name)
            if result:
                self.results.append(result)
        
        return self.results
    
    def generate_report(self):
        """Generate detailed comparison report"""
        print("\n" + "="*70)
        print("RESULTS REPORT")
        print("="*70)
        
        # Filter successful tests
        successful = [r for r in self.results if r["success"] and r["latency_ms"]]
        successful.sort(key=lambda x: x["latency_ms"])
        
        print(f"\n✓ Successful: {len(successful)}/{len(self.results)}")
        
        if successful:
            print(f"\n{'Rank':<6} {'Model':<30} {'Latency':<12} {'Speed vs Winner'}")
            print("─" * 70)
            
            best_latency = successful[0]["latency_ms"]
            
            for rank, result in enumerate(successful, 1):
                latency = result["latency_ms"]
                model_name = result["model_name"][:28]
                
                if rank == 1:
                    speed_comp = "🏆 WINNER"
                else:
                    diff_ms = latency - best_latency
                    pct = (diff_ms / best_latency) * 100
                    speed_comp = f"+{pct:.1f}% slower"
                
                print(f"{rank:<6} {model_name:<30} {latency:>10.0f}ms  {speed_comp}")
        
        # Summary statistics
        if successful:
            latencies = [r["latency_ms"] for r in successful]
            avg = sum(latencies) / len(latencies)
            min_l = min(latencies)
            max_l = max(latencies)
            
            print(f"\n{'STATISTICS':<40}")
            print("─" * 70)
            print(f"Average latency: {avg:.0f}ms")
            print(f"Fastest: {min_l:.0f}ms")
            print(f"Slowest: {max_l:.0f}ms")
            print(f"Range: {max_l - min_l:.0f}ms")
        
        # Failed tests
        failed = [r for r in self.results if not r["success"] and not r.get("expected_timeout")]
        expected_timeouts = [r for r in self.results if r.get("expected_timeout")]
        if failed:
            print(f"\n✗ Failed: {len(failed)}")
            for result in failed:
                print(f"  - {result['model_name']}: {result['response_preview']}")

        if expected_timeouts:
            print(f"\n⚠ Expected timeouts: {len(expected_timeouts)}")
            for result in expected_timeouts:
                print(f"  - {result['model_name']}: TIMEOUT (expected)")
        
        # Save detailed results
        output_file = Path("latency_comparison_comprehensive.json")
        with open(output_file, "w") as f:
            json.dump({
                "timestamp": self.timestamp,
                "prompt": TEST_PROMPT,
                "total_models": len(self.results),
                "successful": len(successful),
                "results": self.results,
            }, f, indent=2)
        
        print(f"\n✓ Detailed results saved to: {output_file}")
        
        return self.results

def main():
    tester = ComprehensiveTest()
    tester.run_all_tests()
    tester.generate_report()

if __name__ == "__main__":
    main()
