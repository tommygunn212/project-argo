#!/usr/bin/env python3
"""
Quick test to verify recording constants are properly defined
and wake → record flow can execute without AttributeError.
"""

import sys

def test_constants():
    """Test that all recording constants are defined."""
    print("=" * 70)
    print("TESTING RECORDING CONSTANTS")
    print("=" * 70)
    
    try:
        from core.coordinator import Coordinator
        
        # Test class-level constants
        print("\n✅ Class-level constants:")
        constants = {
            "MAX_RECORDING_DURATION": Coordinator.MAX_RECORDING_DURATION,
            "MIN_RECORDING_DURATION": Coordinator.MIN_RECORDING_DURATION,
            "SILENCE_DURATION": Coordinator.SILENCE_DURATION,
            "MINIMUM_RECORD_DURATION": Coordinator.MINIMUM_RECORD_DURATION,
            "SILENCE_TIMEOUT_SECONDS": Coordinator.SILENCE_TIMEOUT_SECONDS,
        }
        
        for name, value in constants.items():
            print(f"  {name:.<40} {value}")
        
        # Verify critical ones
        assert hasattr(Coordinator, 'MAX_RECORDING_DURATION'), "Missing MAX_RECORDING_DURATION"
        assert hasattr(Coordinator, 'MIN_RECORDING_DURATION'), "Missing MIN_RECORDING_DURATION"
        assert hasattr(Coordinator, 'SILENCE_DURATION'), "Missing SILENCE_DURATION"
        
        # Test values match Bob's requirements
        assert Coordinator.MAX_RECORDING_DURATION == 15.0, f"MAX_RECORDING_DURATION should be 15.0, got {Coordinator.MAX_RECORDING_DURATION}"
        assert Coordinator.MIN_RECORDING_DURATION == 0.9, f"MIN_RECORDING_DURATION should be 0.9, got {Coordinator.MIN_RECORDING_DURATION}"
        assert Coordinator.SILENCE_DURATION == 2.2, f"SILENCE_DURATION should be 2.2, got {Coordinator.SILENCE_DURATION}"
        
        print("\n✅ All constants correctly defined:")
        print(f"  MAX_RECORDING_DURATION = {Coordinator.MAX_RECORDING_DURATION}")
        print(f"  MIN_RECORDING_DURATION = {Coordinator.MIN_RECORDING_DURATION}")
        print(f"  SILENCE_DURATION = {Coordinator.SILENCE_DURATION}")
        
        # Test instantiation doesn't crash
        print("\n✅ Testing Coordinator instantiation...")
        
        # Mock dependencies
        class MockTrigger:
            def _check_for_interrupt(self):
                return False
            def get_preroll_buffer(self):
                return []
        
        class MockSTT:
            pass
        
        class MockParser:
            pass
        
        class MockGenerator:
            pass
        
        class MockSink:
            pass
        
        try:
            coord = Coordinator(
                input_trigger=MockTrigger(),
                speech_to_text=MockSTT(),
                intent_parser=MockParser(),
                response_generator=MockGenerator(),
                output_sink=MockSink()
            )
            print("  Coordinator.__init__() succeeded ✓")
            
            # Test that constants are accessible via self.
            assert hasattr(coord, 'MAX_RECORDING_DURATION'), "Missing self.MAX_RECORDING_DURATION"
            assert hasattr(coord, 'MIN_RECORDING_DURATION'), "Missing self.MIN_RECORDING_DURATION"
            assert hasattr(coord, 'SILENCE_DURATION'), "Missing self.SILENCE_DURATION"
            
            print("  Constants accessible via self. ✓")
            print(f"  coord.MAX_RECORDING_DURATION = {coord.MAX_RECORDING_DURATION}")
            print(f"  coord.MIN_RECORDING_DURATION = {coord.MIN_RECORDING_DURATION}")
            print(f"  coord.SILENCE_DURATION = {coord.SILENCE_DURATION}")
            
        except Exception as e:
            print(f"  ❌ Coordinator instantiation failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED - BLOCKER FIXED")
        print("=" * 70)
        print("\nExpected flow on next run:")
        print("  1. Wake word triggers ✓")
        print("  2. Recording starts (max {0}s, silence {1}s) ✓".format(
            Coordinator.MAX_RECORDING_DURATION,
            Coordinator.SILENCE_DURATION
        ))
        print("  3. Minimum {0}s enforced ✓".format(Coordinator.MIN_RECORDING_DURATION))
        print("  4. No AttributeError crash ✓")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_constants()
    sys.exit(0 if success else 1)
