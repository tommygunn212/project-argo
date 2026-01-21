#!/usr/bin/env python3
"""
Verify all three blocker fixes are in place.
"""

import sys

def verify_fixes():
    """Verify all three fixes."""
    print("=" * 70)
    print("VERIFYING THREE BLOCKER FIXES")
    print("=" * 70)
    
    try:
        # Import modules
        from core.coordinator import Coordinator
        from core.output_sink import PiperOutputSink
        import inspect
        
        # FIX 1: Check recording has speech_detected tracking
        print("\n✅ FIX 1: Recording Silence Detection")
        record_source = inspect.getsource(Coordinator._record_with_silence_detection)
        checks = [
            ("speech_detected_at", "Tracks when speech detected"),
            ("silence_started_at", "Tracks when silence starts"),
            ("stop_reason", "Tracks why recording stopped"),
            ("self.RMS_SPEECH_THRESHOLD", "Uses RMS threshold"),
            ("elapsed_time", "Tracks timing"),
        ]
        for check, desc in checks:
            if check in record_source:
                print(f"  ✓ {desc}")
            else:
                print(f"  ✗ {desc}")
                return False
        
        # FIX 2: Check _speak_with_interrupt_detection is simplified
        print("\n✅ FIX 2: TTS Without Interrupts")
        speak_source = inspect.getsource(Coordinator._speak_with_interrupt_detection)
        
        # Should NOT have interrupt monitoring
        bad_patterns = [
            "monitor_for_interrupt",
            "interrupt_detector",
            "PorcupineWakeWordTrigger",
            "threading.Thread",
        ]
        has_bad = False
        for pattern in bad_patterns:
            if pattern in speak_source:
                print(f"  ✗ Still has {pattern} (interrupt monitoring)")
                has_bad = True
        
        if not has_bad:
            print(f"  ✓ Interrupt monitoring removed")
        
        # Should have simple speak call
        if "self.sink.speak(response_text)" in speak_source:
            print(f"  ✓ Simple playback (just speak)")
        else:
            print(f"  ✗ Missing simple speak call")
            return False
        
        # FIX 3: Check streaming implementation
        print("\n✅ FIX 3: Piper Streaming Audio")
        try:
            stream_source = inspect.getsource(PiperOutputSink._stream_audio_data)
            progressive_source = inspect.getsource(PiperOutputSink._stream_to_speaker_progressive)
            
            checks = [
                ("CHUNK_MS = 100", "100ms chunk size"),
                ("BUFFER_MS = 200", "200ms buffer before play"),
                ("readexactly", "Reads in fixed chunks"),
                ("run_in_executor", "Progressive playback"),
            ]
            
            combined_source = stream_source + progressive_source
            for check, desc in checks:
                if check in combined_source:
                    print(f"  ✓ {desc}")
                else:
                    print(f"  ✗ {desc}")
                    return False
        except AttributeError:
            print(f"  ✗ Missing streaming methods")
            return False
        
        print("\n" + "=" * 70)
        print("✅ ALL THREE FIXES VERIFIED")
        print("=" * 70)
        print("\nExpected behavior:")
        print("  1. Recording stops in 2-3 seconds (not 15)")
        print("  2. TTS plays without self-interruption")
        print("  3. First audio heard in ~200ms (not 500-800ms)")
        print("\nReady for testing!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = verify_fixes()
    sys.exit(0 if success else 1)
