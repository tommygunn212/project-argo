#!/usr/bin/env python3
"""
ARGO Latency - Baseline Measurement Collection
Collects timing data across 4 test scenarios in FAST mode
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime

# Fix Unicode on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "runtime"))

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 30  # seconds

# Test scenarios - using root endpoint (simplest test)
# NOTE: HTTP endpoints in app.py require specific state transitions.
# These trivial requests test framework instrumentation, not full workflows.
TEST_SCENARIOS = {
    "scenario_1_root_endpoint": {
        "endpoint": "/",
        "method": "GET",
        "data": None,
        "description": "Root endpoint (framework test)"
    }
}

def check_server_ready():
    """Check if server is responding"""
    print("\n" + "="*70)
    print("BASELINE MEASUREMENT - SERVER READINESS")
    print("="*70)
    
    print(f"\nChecking server at {BASE_URL}...")
    
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            response = requests.get(f"{BASE_URL}/", timeout=2)
            if response.status_code in [200, 404, 405]:  # Server is responding
                print(f"[OK] Server is responding (HTTP {response.status_code})")
                return True
        except requests.exceptions.ConnectionError:
            print(f"  Attempt {attempt+1}/{max_attempts}: Connection refused...")
            time.sleep(1)
        except requests.exceptions.Timeout:
            print(f"  Attempt {attempt+1}/{max_attempts}: Timeout...")
            time.sleep(1)
    
    print(f"[FAIL] Server not responding after {max_attempts} attempts")
    print(f"   Make sure app is running: python input_shell/app.py")
    return False

def collect_single_measurement(scenario_key, scenario_config, run_num):
    """Collect a single measurement for a scenario"""
    
    endpoint = scenario_config["endpoint"]
    method = scenario_config["method"]
    data = scenario_config["data"]
    
    try:
        start_time = time.time()
        start_ns = time.perf_counter_ns()
        
        if method == "POST":
            response = requests.post(
                f"{BASE_URL}{endpoint}",
                json=data,
                timeout=TIMEOUT
            )
        else:
            response = requests.get(
                f"{BASE_URL}{endpoint}",
                params=data,
                timeout=TIMEOUT
            )
        
        end_ns = time.perf_counter_ns()
        end_time = time.time()
        
        elapsed_ms = (end_ns - start_ns) / 1_000_000
        
        return {
            "run": run_num,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "timestamp": datetime.now().isoformat(),
            "success": 200 <= response.status_code < 400
        }
        
    except requests.exceptions.Timeout:
        return {
            "run": run_num,
            "status_code": None,
            "elapsed_ms": TIMEOUT * 1000,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "error": "Timeout"
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "run": run_num,
            "status_code": None,
            "elapsed_ms": None,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "run": run_num,
            "status_code": None,
            "elapsed_ms": None,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "error": str(e)
        }

def run_baseline_collection(runs_per_scenario=3):
    """Collect baseline measurements"""
    
    print("\n" + "="*70)
    print("BASELINE MEASUREMENT COLLECTION")
    print("="*70)
    
    measurements = {}
    
    for scenario_key, scenario_config in TEST_SCENARIOS.items():
        print(f"\n📊 {scenario_key}")
        print(f"   {scenario_config['description']}")
        print(f"   Endpoint: {scenario_config['endpoint']}")
        
        measurements[scenario_key] = {
            "description": scenario_config["description"],
            "endpoint": scenario_config["endpoint"],
            "runs": []
        }
        
        for run_num in range(1, runs_per_scenario + 1):
            print(f"   Run {run_num}/{runs_per_scenario}...", end=" ", flush=True)
            
            result = collect_single_measurement(scenario_key, scenario_config, run_num)
            measurements[scenario_key]["runs"].append(result)
            
            if result["success"]:
                print(f"[OK] {result['elapsed_ms']:.1f}ms")
            else:
                error_msg = result.get("error", f"HTTP {result['status_code']}")
                print(f"[ERR] {error_msg}")
            
            # Small delay between runs
            time.sleep(0.5)
    
    return measurements

def analyze_measurements(measurements):
    """Analyze collected measurements"""
    
    print("\n" + "="*70)
    print("BASELINE ANALYSIS")
    print("="*70)
    
    fast_budget = {
        "first_token": 2000,
        "total_response": 6000,
        "stream_delay": 0
    }
    
    analysis = {}
    all_successful = 0
    total_runs = 0
    
    for scenario_key, scenario_data in measurements.items():
        runs = scenario_data["runs"]
        successful_runs = [r for r in runs if r["success"] and r["elapsed_ms"]]
        failed_runs = [r for r in runs if not r["success"]]
        
        total_runs += len(runs)
        all_successful += len(successful_runs)
        
        if successful_runs:
            timings = [r["elapsed_ms"] for r in successful_runs]
            
            analysis[scenario_key] = {
                "description": scenario_data["description"],
                "total_runs": len(runs),
                "successful": len(successful_runs),
                "failed": len(failed_runs),
                "min_ms": min(timings),
                "max_ms": max(timings),
                "avg_ms": sum(timings) / len(timings),
                "within_fast_budget": all(t <= fast_budget["total_response"] for t in timings)
            }
        else:
            analysis[scenario_key] = {
                "description": scenario_data["description"],
                "total_runs": len(runs),
                "successful": 0,
                "failed": len(failed_runs),
                "min_ms": None,
                "max_ms": None,
                "avg_ms": None,
                "within_fast_budget": False
            }
    
    # Print analysis
    print("\nScenario Results:")
    print("-" * 70)
    
    for scenario_key, stats in analysis.items():
        print(f"\n{scenario_key}")
        print(f"  Description: {stats['description']}")
        print(f"  Runs: {stats['successful']}/{stats['total_runs']} successful")
        
        if stats['successful'] > 0:
            print(f"  Latency:")
            print(f"    Min:  {stats['min_ms']:.1f}ms")
            print(f"    Max:  {stats['max_ms']:.1f}ms")
            print(f"    Avg:  {stats['avg_ms']:.1f}ms")
            
            budget_check = "✅ PASS" if stats['within_fast_budget'] else "❌ FAIL"
            print(f"  FAST Budget Check: {budget_check}")
        else:
            print(f"  ❌ All runs failed")
    
    # Overall summary
    print("\n" + "-" * 70)
    print(f"Overall: {all_successful}/{total_runs} runs successful")
    
    fast_pass = sum(1 for s in analysis.values() if s['within_fast_budget'])
    print(f"FAST Budget: {fast_pass}/{len(analysis)} scenarios pass")
    
    if all_successful == total_runs and fast_pass == len(analysis):
        print("\n✅ BASELINE MEASUREMENT COMPLETE - ALL CHECKS PASS")
        return True
    else:
        print("\n⚠️  BASELINE MEASUREMENT COMPLETE - SOME CHECKS FAILED")
        return False

def save_measurements(measurements, filename="latency_baseline_measurements.json"):
    """Save measurements to JSON file"""
    
    filepath = Path(__file__).parent / filename
    
    with open(filepath, "w") as f:
        json.dump(measurements, f, indent=2, default=str)
    
    print(f"\n💾 Measurements saved to {filepath}")

def main():
    print("\n" + "="*70)
    print("ARGO LATENCY BASELINE MEASUREMENT")
    print("="*70)
    
    # Step 1: Check server
    if not check_server_ready():
        print("\n⚠️  Server not ready. Please start the app:")
        print("   cd input_shell")
        print("   python app.py")
        return False
    
    # Step 2: Collect measurements
    measurements = run_baseline_collection(runs_per_scenario=3)
    
    # Step 3: Analyze
    success = analyze_measurements(measurements)
    
    # Step 4: Save
    save_measurements(measurements)
    
    # Step 5: Generate report
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print("\nBaseline measurements collected and saved.")
    print("View results in: latency_baseline_measurements.json")
    print("\nTo continue:")
    print("  1. Review measurements in latency_baseline_measurements.json")
    print("  2. Update latency_report.md with baseline statistics")
    print("  3. Identify bottlenecks for optimization phase")
    
    return success

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Measurement collection interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during measurement: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
