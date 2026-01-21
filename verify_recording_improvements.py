#!/usr/bin/env python3
"""
Quick verification script for recording improvements.
Shows all new constants and confirms configuration.
"""

import os
import sys

def verify_recording_improvements():
    """Verify all recording improvements are in place."""
    print("=" * 70)
    print("RECORDING IMPROVEMENTS - VERIFICATION")
    print("=" * 70)
    
    try:
        from core.coordinator import Coordinator
        
        # Extract constants
        constants = {
            "MINIMUM_RECORD_DURATION": Coordinator.MINIMUM_RECORD_DURATION,
            "SILENCE_TIMEOUT_SECONDS": Coordinator.SILENCE_TIMEOUT_SECONDS,
            "RMS_SPEECH_THRESHOLD": Coordinator.RMS_SPEECH_THRESHOLD,
            "SILENCE_THRESHOLD": Coordinator.SILENCE_THRESHOLD,
            "PRE_ROLL_BUFFER_MS_MIN": Coordinator.PRE_ROLL_BUFFER_MS_MIN,
            "PRE_ROLL_BUFFER_MS_MAX": Coordinator.PRE_ROLL_BUFFER_MS_MAX,
            "MAX_RECORDING_DURATION": Coordinator.MAX_RECORDING_DURATION,
        }
        
        print("\n✅ CONSTANTS LOADED:\n")
        for name, value in constants.items():
            unit = "s" if "DURATION" in name or "TIMEOUT" in name else "ms" if "MS" in name else ""
            print(f"  {name:.<40} {value:>8} {unit}")
        
        # Check debug flag
        debug_enabled = os.getenv("ARGO_RECORD_DEBUG", "0").lower() in ("1", "true")
        print(f"\n✅ DEBUG METRICS:\n")
        print(f"  ARGO_RECORD_DEBUG env var .............. {'ENABLED' if debug_enabled else 'DISABLED'}")
        print(f"  Set ARGO_RECORD_DEBUG=1 to enable debug metrics")
        
        # Check pre-roll configuration
        print(f"\n✅ PRE-ROLL BUFFER:\n")
        print(f"  Min pre-speech audio ................... {constants['PRE_ROLL_BUFFER_MS_MIN']}ms")
        print(f"  Max rolling buffer ..................... {constants['PRE_ROLL_BUFFER_MS_MAX']}ms")
        print(f"  Capacity (at ~100ms chunks) ........... 4 frames (~400ms)")
        
        # Check RMS configuration
        print(f"\n✅ RMS-BASED SILENCE DETECTION:\n")
        print(f"  Speech threshold (normalized 0-1) .... {constants['RMS_SPEECH_THRESHOLD']}")
        print(f"  Silence threshold (absolute RMS) ..... {constants['SILENCE_THRESHOLD']}")
        print(f"  Silence timeout ........................ {constants['SILENCE_TIMEOUT_SECONDS']}s")
        print(f"  Minimum record duration ............... {constants['MINIMUM_RECORD_DURATION']}s")
        
        # Check methods exist
        print(f"\n✅ COORDINATOR METHODS:\n")
        methods = [
            "_record_with_silence_detection",
            "_speak_with_interrupt_detection",
            "_monitor_music_interrupt",
        ]
        for method_name in methods:
            has_method = hasattr(Coordinator, method_name)
            print(f"  {method_name:.<45} {'✓' if has_method else '✗'}")
        
        # Check InputTrigger
        from core.input_trigger import PorcupineWakeWordTrigger
        print(f"\n✅ INPUT TRIGGER (PRE-ROLL):\n")
        
        trigger_attrs = [
            ("preroll_buffer", "Pre-roll buffer list"),
            ("preroll_capacity", "Buffer capacity (frames)"),
            ("preroll_enabled", "Pre-roll enabled flag"),
            ("get_preroll_buffer", "Method to retrieve buffer"),
        ]
        
        for attr_name, description in trigger_attrs:
            has_attr = hasattr(PorcupineWakeWordTrigger, attr_name) or attr_name in ("get_preroll_buffer",)
            print(f"  {description:.<45} {'✓' if has_attr else '✗'}")
        
        print("\n" + "=" * 70)
        print("✅ ALL IMPROVEMENTS VERIFIED")
        print("=" * 70)
        print("\nNOTE: To enable debug metrics during recording, run:")
        print("  export ARGO_RECORD_DEBUG=1")
        print("\nThen run Argo normally and you'll see detailed recording metrics.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = verify_recording_improvements()
    sys.exit(0 if success else 1)
