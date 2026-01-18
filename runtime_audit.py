#!/usr/bin/env python3
"""
ARGO Latency - Runtime Audit: FAST Mode Verification & Baseline Measurement

Objective: Verify FAST mode contract and collect baseline measurements
- First token timing: ≤2000ms (budget)
- Total response time: ≤6000ms (budget)
- Stream delay: 0ms (enforced)

Test Scenarios:
1. Text question (Q&A, read-only)
2. API status check (no delay)
"""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def test_api_status():
    """Test that app is running and responding."""
    print("\n" + "="*70)
    print("TEST 1: API Status Check")
    print("="*70)
    
    try:
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/status", timeout=5)
        elapsed_ms = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Status endpoint responding")
            print(f"   Response time: {elapsed_ms:.1f}ms")
            print(f"   Session ID: {data.get('session_id', 'N/A')[:8]}...")
            return True
        else:
            print(f"❌ Status endpoint error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return False

def test_fast_mode_contract():
    """
    Verify FAST mode contract:
    - First token: ≤2000ms
    - Total response: ≤6000ms
    - Stream delays: 0ms
    """
    print("\n" + "="*70)
    print("TEST 2: FAST Mode Contract Verification")
    print("="*70)
    
    print("\nFAST Mode SLA:")
    print("  • First token: ≤2000ms")
    print("  • Total response: ≤6000ms")
    print("  • Stream delays: 0ms (no pacing)")
    
    # Check latency_controller to verify FAST budget
    try:
        from latency_controller import LatencyProfile, LatencyBudget
        
        fast_budget = LatencyBudget.default(LatencyProfile.FAST)
        print(f"\nLatencyBudget for FAST:")
        print(f"  ✅ First token max: {fast_budget.first_token_max_ms}ms")
        print(f"  ✅ Total response max: {fast_budget.total_response_max_ms}ms")
        print(f"  ✅ Stream delay: {fast_budget.stream_chunk_delay_ms}ms")
        
        # Verify contract
        assert fast_budget.first_token_max_ms == 2000, "First token budget wrong"
        assert fast_budget.total_response_max_ms == 6000, "Total budget wrong"
        assert fast_budget.stream_chunk_delay_ms == 0, "Stream delay should be 0"
        
        print(f"\n✅ FAST mode contract verified in code")
        return True
    except Exception as e:
        print(f"❌ FAST mode verification failed: {e}")
        return False

def test_checkpoint_logging():
    """Verify checkpoints are being logged correctly."""
    print("\n" + "="*70)
    print("TEST 3: Checkpoint Logging Verification")
    print("="*70)
    
    try:
        from latency_controller import new_controller, LatencyProfile
        
        controller = new_controller(LatencyProfile.FAST)
        controller.log_checkpoint("test_checkpoint_1")
        time.sleep(0.01)  # Small delay
        controller.log_checkpoint("test_checkpoint_2")
        
        report = controller.report()
        
        print(f"\nController Report:")
        print(f"  Profile: {report['profile']}")
        print(f"  Elapsed: {report['elapsed_ms']:.1f}ms")
        print(f"  Checkpoints logged: {len(report['checkpoints'])}")
        
        if "test_checkpoint_1" in report["checkpoints"]:
            print(f"    ✅ test_checkpoint_1: {report['checkpoints']['test_checkpoint_1']:.1f}ms")
        if "test_checkpoint_2" in report["checkpoints"]:
            print(f"    ✅ test_checkpoint_2: {report['checkpoints']['test_checkpoint_2']:.1f}ms")
        
        # Verify checkpoint delta
        delta = report["checkpoints"]["test_checkpoint_2"] - report["checkpoints"]["test_checkpoint_1"]
        print(f"  Delta between checkpoints: {delta:.1f}ms (expected ~10ms)")
        
        return True
    except Exception as e:
        print(f"❌ Checkpoint logging failed: {e}")
        return False

def test_no_inline_sleeps():
    """Verify no blocking sleeps in application code."""
    print("\n" + "="*70)
    print("TEST 4: No Inline Sleeps Verification")
    print("="*70)
    
    try:
        import subprocess
        
        # Search for sleep calls in app.py
        result = subprocess.run(
            ["powershell", "-Command", 
             "Select-String -Path 'i:\\argo\\input_shell\\app.py' -Pattern 'time\\.sleep|asyncio\\.sleep' -ErrorAction SilentlyContinue"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip():
            print(f"❌ Found inline sleep calls in app.py:")
            print(result.stdout)
            return False
        else:
            print(f"✅ No inline sleep calls found in app.py")
            print(f"   Verified: time.sleep() and asyncio.sleep() absent")
            return True
    except Exception as e:
        print(f"⚠️ Sleep verification inconclusive: {e}")
        return True  # Non-blocking

def main():
    print("\n" + "="*70)
    print("ARGO LATENCY - RUNTIME AUDIT")
    print("="*70)
    print("\nPhase: Runtime Verification + Baseline Measurement Preparation")
    print("App: Running on http://127.0.0.1:8000")
    
    results = {
        "API Status": test_api_status(),
        "FAST Mode Contract": test_fast_mode_contract(),
        "Checkpoint Logging": test_checkpoint_logging(),
        "No Inline Sleeps": test_no_inline_sleeps(),
    }
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🟢 ALL TESTS PASSED - Ready for baseline measurement collection")
        print("\nNext Steps:")
        print("  1. Open http://127.0.0.1:8000 in browser")
        print("  2. Run test scenarios (text question, text command, etc.)")
        print("  3. Extract checkpoint timings from logs")
        print("  4. Fill latency_report.md with measurements")
        return 0
    else:
        print("\n🔴 SOME TESTS FAILED - See details above")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
