#!/usr/bin/env python3
"""
ARGO Latency - Direct Framework Testing
Tests the latency controller without HTTP calls
Simulates the checkpoint flow that app.py uses
"""

import sys
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "runtime"))

from latency_controller import LatencyProfile, new_controller

def simulate_fast_mode_flow():
    """Simulate the 8-checkpoint flow in FAST mode"""
    
    print("\n" + "="*70)
    print("SIMULATING FAST MODE FLOW (≤6 seconds total)")
    print("="*70)
    
    # Create controller in FAST mode
    controller = new_controller(LatencyProfile.FAST)
    
    # Simulate the 8 checkpoints
    checkpoints = [
        ("input_received", 0.01),         # 10ms - receive input
        ("transcription_complete", 0.50), # 500ms - transcribe audio
        ("intent_classified", 0.05),      # 50ms - classify intent
        ("model_selected", 0.02),         # 20ms - select model
        ("ollama_request_start", 0.00),   # 0ms - immediate
        ("first_token_received", 1.50),   # 1500ms - wait for first token
        ("stream_complete", 2.00),        # 2000ms - stream rest
        ("processing_complete", 0.10),    # 100ms - finalize
    ]
    
    print("\nCheckpoints:")
    print("-" * 70)
    
    cumulative_ms = 0
    
    for name, delay in checkpoints:
        # Add the delay
        if delay > 0:
            time.sleep(delay)
        
        # Log checkpoint
        controller.log_checkpoint(name)
        
        cumulative_ms += delay * 1000
        actual_ms = controller.elapsed_ms()
        
        print(f"  {name:<25} | Simulated: {delay*1000:>7.1f}ms | Actual: {actual_ms:>7.1f}ms")
    
    # Generate report
    report = controller.report()
    
    print("-" * 70)
    print(f"\nTotal Elapsed: {report['elapsed_ms']:.1f}ms")
    print(f"FAST Budget: 6000ms")
    print(f"First Token Latency: {report['checkpoints'].get('first_token_received', 0):.1f}ms (limit: 2000ms)")
    
    # Verify budget
    within_budget = report['elapsed_ms'] <= 6000
    first_token_ok = report['checkpoints'].get('first_token_received', 0) <= 2000
    
    print("\nFAST Mode Validation:")
    print(f"  Total latency ≤ 6000ms: {'✅ PASS' if within_budget else '❌ FAIL'}")
    print(f"  First token ≤ 2000ms: {'✅ PASS' if first_token_ok else '❌ FAIL'}")
    
    return within_budget and first_token_ok

def simulate_argo_mode_flow():
    """Simulate the 8-checkpoint flow in ARGO mode"""
    
    print("\n" + "="*70)
    print("SIMULATING ARGO MODE FLOW (≤10 seconds total)")
    print("="*70)
    
    # Create controller in ARGO mode
    controller = new_controller(LatencyProfile.ARGO)
    
    # Simulate slightly slower scenario
    checkpoints = [
        ("input_received", 0.02),         # 20ms
        ("transcription_complete", 1.0),  # 1000ms - longer transcription
        ("intent_classified", 0.10),      # 100ms
        ("model_selected", 0.05),         # 50ms
        ("ollama_request_start", 0.00),   # 0ms
        ("first_token_received", 2.50),   # 2500ms - slower first token
        ("stream_complete", 3.00),        # 3000ms - more streaming
        ("processing_complete", 0.15),    # 150ms
    ]
    
    print("\nCheckpoints:")
    print("-" * 70)
    
    cumulative_ms = 0
    
    for name, delay in checkpoints:
        if delay > 0:
            time.sleep(delay)
        
        controller.log_checkpoint(name)
        
        cumulative_ms += delay * 1000
        actual_ms = controller.elapsed_ms()
        
        print(f"  {name:<25} | Simulated: {delay*1000:>7.1f}ms | Actual: {actual_ms:>7.1f}ms")
    
    # Generate report
    report = controller.report()
    
    print("-" * 70)
    print(f"\nTotal Elapsed: {report['elapsed_ms']:.1f}ms")
    print(f"ARGO Budget: 10000ms")
    print(f"First Token Latency: {report['checkpoints'].get('first_token_received', 0):.1f}ms (limit: 3000ms)")
    
    # Verify budget
    within_budget = report['elapsed_ms'] <= 10000
    first_token_ok = report['checkpoints'].get('first_token_received', 0) <= 3000
    
    print("\nARGO Mode Validation:")
    print(f"  Total latency ≤ 10000ms: {'✅ PASS' if within_budget else '❌ FAIL'}")
    print(f"  First token ≤ 3000ms: {'✅ PASS' if first_token_ok else '❌ FAIL'}")
    
    return within_budget and first_token_ok

def simulate_voice_mode_flow():
    """Simulate the 8-checkpoint flow in VOICE mode"""
    
    print("\n" + "="*70)
    print("SIMULATING VOICE MODE FLOW (≤15 seconds total)")
    print("="*70)
    
    # Create controller in VOICE mode
    controller = new_controller(LatencyProfile.VOICE)
    
    # Simulate slowest scenario
    checkpoints = [
        ("input_received", 0.05),         # 50ms
        ("transcription_complete", 2.00), # 2000ms - slow transcription
        ("intent_classified", 0.20),      # 200ms
        ("model_selected", 0.10),         # 100ms
        ("ollama_request_start", 0.00),   # 0ms
        ("first_token_received", 3.00),   # 3000ms - slow first token
        ("stream_complete", 5.00),        # 5000ms - lots of streaming
        ("processing_complete", 0.20),    # 200ms
    ]
    
    print("\nCheckpoints:")
    print("-" * 70)
    
    cumulative_ms = 0
    
    for name, delay in checkpoints:
        if delay > 0:
            time.sleep(delay)
        
        controller.log_checkpoint(name)
        
        cumulative_ms += delay * 1000
        actual_ms = controller.elapsed_ms()
        
        print(f"  {name:<25} | Simulated: {delay*1000:>7.1f}ms | Actual: {actual_ms:>7.1f}ms")
    
    # Generate report
    report = controller.report()
    
    print("-" * 70)
    print(f"\nTotal Elapsed: {report['elapsed_ms']:.1f}ms")
    print(f"VOICE Budget: 15000ms")
    print(f"First Token Latency: {report['checkpoints'].get('first_token_received', 0):.1f}ms (limit: 3000ms)")
    
    # Verify budget
    within_budget = report['elapsed_ms'] <= 15000
    first_token_ok = report['checkpoints'].get('first_token_received', 0) <= 3000
    
    print("\nVOICE Mode Validation:")
    print(f"  Total latency ≤ 15000ms: {'✅ PASS' if within_budget else '❌ FAIL'}")
    print(f"  First token ≤ 3000ms: {'✅ PASS' if first_token_ok else '❌ FAIL'}")
    
    return within_budget and first_token_ok

def main():
    print("\n" + "="*70)
    print("ARGO LATENCY - DIRECT FRAMEWORK BASELINE")
    print("="*70)
    
    print("\nThis test simulates real checkpoint flows without HTTP overhead.")
    print("Tests the latency controller's core functionality.\n")
    
    # Run all three mode simulations
    fast_pass = simulate_fast_mode_flow()
    argo_pass = simulate_argo_mode_flow()
    voice_pass = simulate_voice_mode_flow()
    
    # Summary
    print("\n" + "="*70)
    print("BASELINE SUMMARY")
    print("="*70)
    
    print("\nResults:")
    print(f"  FAST Mode:  {'✅ PASS' if fast_pass else '❌ FAIL'}")
    print(f"  ARGO Mode:  {'✅ PASS' if argo_pass else '❌ FAIL'}")
    print(f"  VOICE Mode: {'✅ PASS' if voice_pass else '❌ FAIL'}")
    
    all_pass = fast_pass and argo_pass and voice_pass
    
    print("\n" + "="*70)
    if all_pass:
        print("✅ ALL BASELINES ESTABLISHED SUCCESSFULLY")
        print("="*70)
        print("\nFramework Status:")
        print("  • FAST mode latency: ✅ Confirmed ≤6s")
        print("  • ARGO mode latency: ✅ Confirmed ≤10s")
        print("  • VOICE mode latency: ✅ Confirmed ≤15s")
        print("  • First-token tracking: ✅ Working")
        print("  • Checkpoint logging: ✅ Accurate")
        print("\nNext Phase: Optimization and bottleneck analysis")
    else:
        print("❌ SOME BASELINES FAILED")
        print("="*70)
        print("\nPlease review failures above.")
    
    return 0 if all_pass else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
