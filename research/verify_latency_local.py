#!/usr/bin/env python3
"""
ARGO Latency - Local Verification
Verify framework is working without requiring running app
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "runtime"))

print("\n" + "="*70)
print("ARGO LATENCY - LOCAL VERIFICATION TESTS")
print("="*70)

# Test 1: Import latency_controller
print("\n[TEST 1] Import latency_controller module")
try:
    from latency_controller import (
        LatencyProfile,
        LatencyBudget,
        LatencyController,
        new_controller,
        checkpoint,
    )
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

# Test 2: Verify FAST mode contract
print("\n[TEST 2] Verify FAST mode contract")
try:
    fast_budget = LatencyBudget.default(LatencyProfile.FAST)
    
    print(f"  FAST Mode SLA:")
    print(f"    First token max: {fast_budget.first_token_max_ms}ms", end="")
    assert fast_budget.first_token_max_ms == 2000
    print(" ✅")
    
    print(f"    Total response max: {fast_budget.total_response_max_ms}ms", end="")
    assert fast_budget.total_response_max_ms == 6000
    print(" ✅")
    
    print(f"    Stream chunk delay: {fast_budget.stream_chunk_delay_ms}ms", end="")
    assert fast_budget.stream_chunk_delay_ms == 0
    print(" ✅")
    
    print("✅ FAST mode contract verified")
except AssertionError as e:
    print(f"❌ Contract mismatch: {e}")
    sys.exit(1)

# Test 3: Verify ARGO mode
print("\n[TEST 3] Verify ARGO mode contract")
try:
    argo_budget = LatencyBudget.default(LatencyProfile.ARGO)
    
    print(f"  ARGO Mode SLA:")
    print(f"    First token max: {argo_budget.first_token_max_ms}ms", end="")
    assert argo_budget.first_token_max_ms == 3000
    print(" ✅")
    
    print(f"    Total response max: {argo_budget.total_response_max_ms}ms", end="")
    assert argo_budget.total_response_max_ms == 10000
    print(" ✅")
    
    print(f"    Stream chunk delay: {argo_budget.stream_chunk_delay_ms}ms", end="")
    assert argo_budget.stream_chunk_delay_ms == 200
    print(" ✅")
    
    print("✅ ARGO mode contract verified")
except AssertionError as e:
    print(f"❌ Contract mismatch: {e}")
    sys.exit(1)

# Test 4: Verify VOICE mode
print("\n[TEST 4] Verify VOICE mode contract")
try:
    voice_budget = LatencyBudget.default(LatencyProfile.VOICE)
    
    print(f"  VOICE Mode SLA:")
    print(f"    First token max: {voice_budget.first_token_max_ms}ms", end="")
    assert voice_budget.first_token_max_ms == 3000
    print(" ✅")
    
    print(f"    Total response max: {voice_budget.total_response_max_ms}ms", end="")
    assert voice_budget.total_response_max_ms == 15000
    print(" ✅")
    
    print(f"    Stream chunk delay: {voice_budget.stream_chunk_delay_ms}ms", end="")
    assert voice_budget.stream_chunk_delay_ms == 300
    print(" ✅")
    
    print("✅ VOICE mode contract verified")
except AssertionError as e:
    print(f"❌ Contract mismatch: {e}")
    sys.exit(1)

# Test 5: Test checkpoint logging
print("\n[TEST 5] Test checkpoint logging")
try:
    import time
    
    controller = new_controller(LatencyProfile.FAST)
    
    controller.log_checkpoint("test_1")
    time.sleep(0.01)
    controller.log_checkpoint("test_2")
    time.sleep(0.01)
    controller.log_checkpoint("test_3")
    
    report = controller.report()
    
    print(f"  Controller created: {report['profile']} mode")
    print(f"  Total elapsed: {report['elapsed_ms']:.1f}ms")
    print(f"  Checkpoints logged: {len(report['checkpoints'])}", end="")
    assert len(report['checkpoints']) == 3
    print(" ✅")
    
    for name, elapsed in report['checkpoints'].items():
        print(f"    {name}: {elapsed:.1f}ms")
    
    print("✅ Checkpoint logging works")
except Exception as e:
    print(f"❌ Checkpoint logging failed: {e}")
    sys.exit(1)

# Test 6: Test report structure
print("\n[TEST 6] Test report structure")
try:
    required_fields = ["profile", "elapsed_ms", "checkpoints", "had_intentional_delays", "exceeded_budget"]
    
    for field in required_fields:
        assert field in report, f"Missing field: {field}"
        print(f"  ✅ {field}: {report[field]}")
    
    print("✅ Report structure valid")
except AssertionError as e:
    print(f"❌ Report invalid: {e}")
    sys.exit(1)

# Test 7: Verify .env loads
print("\n[TEST 7] Verify .env configuration")
try:
    import os
    from dotenv import load_dotenv
    
    load_dotenv(Path(__file__).parent / ".env")
    
    profile_name = os.getenv("ARGO_LATENCY_PROFILE", "ARGO")
    print(f"  ARGO_LATENCY_PROFILE: {profile_name}", end="")
    assert profile_name in ["FAST", "ARGO", "VOICE"]
    print(" ✅")
    
    max_delay = os.getenv("ARGO_MAX_INTENTIONAL_DELAY_MS", "1200")
    print(f"  ARGO_MAX_INTENTIONAL_DELAY_MS: {max_delay}ms ✅")
    
    stream_delay = os.getenv("ARGO_STREAM_CHUNK_DELAY_MS", "200")
    print(f"  ARGO_STREAM_CHUNK_DELAY_MS: {stream_delay}ms ✅")
    
    log_latency = os.getenv("ARGO_LOG_LATENCY", "false")
    print(f"  ARGO_LOG_LATENCY: {log_latency} ✅")
    
    print("✅ .env configuration loaded")
except Exception as e:
    print(f"❌ .env loading failed: {e}")
    sys.exit(1)

# Summary
print("\n" + "="*70)
print("VERIFICATION SUMMARY")
print("="*70)
print("\n✅ ALL LOCAL TESTS PASSED")
print("\nFramework Status:")
print("  • Latency controller: Operational ✅")
print("  • FAST mode contract: Enforced ✅")
print("  • ARGO mode contract: Enforced ✅")
print("  • VOICE mode contract: Enforced ✅")
print("  • Checkpoint logging: Working ✅")
print("  • Configuration: Loaded ✅")
print("  • Report structure: Valid ✅")

print("\nNext Steps:")
print("  1. Open http://127.0.0.1:8000 in browser")
print("  2. Run test scenarios to collect actual measurements")
print("  3. Verify first-token latency ≤2000ms in FAST mode")
print("  4. Fill latency_report.md with baseline data")

print("\n🟢 Framework ready for runtime measurement\n")
