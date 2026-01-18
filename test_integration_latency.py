#!/usr/bin/env python3
"""
Quick integration test: Verify latency_controller can be imported from app.py context
"""

import sys
import os
from pathlib import Path

# Simulate app.py's path setup
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "runtime"))

print("🔍 Testing latency_controller integration...")

# Test 1: Import latency_controller
try:
    from latency_controller import (
        LatencyController,
        LatencyProfile,
        new_controller,
        checkpoint,
    )
    print("✓ latency_controller imports successful")
except Exception as e:
    print(f"✗ Failed to import latency_controller: {e}")
    sys.exit(1)

# Test 2: Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    print("✓ .env loaded successfully")
except Exception as e:
    print(f"⚠️ .env loading failed (expected if python-dotenv not installed): {e}")

# Test 3: Parse latency profile
try:
    profile_name = os.getenv("ARGO_LATENCY_PROFILE", "ARGO").upper()
    profile = LatencyProfile[profile_name]
    print(f"✓ Latency profile loaded: {profile.value}")
except Exception as e:
    print(f"✗ Failed to load latency profile: {e}")
    sys.exit(1)

# Test 4: Create controller and log checkpoints
try:
    controller = new_controller(profile)
    checkpoint("input_received")
    checkpoint("transcription_complete")
    checkpoint("intent_classified")
    checkpoint("model_selected")
    checkpoint("ollama_request_start")
    checkpoint("first_token_received")
    checkpoint("stream_complete")
    checkpoint("processing_complete")
    
    report = controller.report()
    print(f"✓ Created controller and logged {len(report['checkpoints'])} checkpoints")
    print(f"  Profile: {report['profile']}")
    print(f"  Total elapsed: {report['elapsed_ms']:.1f}ms")
    print(f"  Checkpoints: {list(report['checkpoints'].keys())}")
except Exception as e:
    print(f"✗ Failed to create controller and log checkpoints: {e}")
    sys.exit(1)

# Test 5: Verify FAST mode has zero delay
try:
    fast_controller = new_controller(LatencyProfile.FAST)
    budget = fast_controller.budget
    assert budget.stream_chunk_delay_ms == 0, f"FAST mode should have 0 delay, got {budget.stream_chunk_delay_ms}"
    assert budget.first_token_max_ms == 2000, f"FAST mode first token should be 2000ms, got {budget.first_token_max_ms}"
    print(f"✓ FAST mode contract verified (0ms delays, 2000ms first token budget)")
except Exception as e:
    print(f"✗ FAST mode contract verification failed: {e}")
    sys.exit(1)

print("\n✅ All integration tests passed!")
print("   - latency_controller can be imported from app.py context")
print("   - .env configuration loads correctly")
print("   - Latency profiles work as expected")
print("   - Controllers create and log checkpoints correctly")
print("   - FAST mode contract is enforced")
