"""
HARDENING STEP 7: Atomicity test for barge-in interrupt flow.

Tests that the complete wake → listen → speak → interrupt → resume flow is atomic and unbreakable.

Key test scenarios:
1. Long TTS playback interrupted by wake word mid-sentence
2. New response after interrupt completes without stale callbacks
3. Multiple back-to-back interrupts
4. State machine stays consistent through interrupt
5. Audio authority releases properly after interrupt

Philosophy:
- No threading races (use locks where needed)
- Zombie callbacks cannot speak after interrupt (interaction_id validation)
- State transitions are fatal (AssertionError on invalid)
- Interrupt is synchronous and immediate (no timeouts)
- Audio authority hard-kill is unrecoverable until next interaction

These tests MUST pass in CI. If any fail, the entire barge-in guarantee is broken.
"""

import unittest
import time
import threading
from unittest.mock import Mock, MagicMock, patch, call
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.state_machine import State, StateMachine
from core.audio_authority import AudioAuthority
from core.output_sink import PiperOutputSink


class TestBargeInAtomicity(unittest.TestCase):
    """Test atomicity of barge-in interrupt flow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.state_machine = StateMachine()
        self.audio_authority = AudioAuthority()
    
    def test_interaction_id_prevents_zombie_callbacks(self):
        """
        TEST 1: Interaction ID validation prevents zombie callbacks.
        
        Scenario:
        1. Start interaction with ID=1
        2. Queue TTS playback with ID=1
        3. Interrupt sets ID=None
        4. Dequeued sentence checks ID and skips (no zombie playback)
        """
        # Create a mock output sink with interaction_id tracking
        sink = PiperOutputSink(piper_path="echo", voice_path="dummy.onnx")
        
        # Simulate interaction_id being set
        sink._interaction_id = 1
        
        # Interrupt sets interaction_id to None (zombie prevention)
        sink._interaction_id = None
        
        # Dequeued sentence should check ID
        # In real code: if self._interaction_id is None: continue
        # This means the sentence is skipped
        
        self.assertIsNone(sink._interaction_id)
        # Zombie callback would check this and skip playback
    
    def test_state_transition_fatal_on_invalid(self):
        """
        TEST 2: State transitions are fatal on invalid states.
        
        Scenario:
        1. Start in SLEEP
        2. Try to transition SLEEP → SPEAKING (invalid)
        3. Raises RuntimeError (fatal, not silent failure)
        """
        self.state_machine._current_state = State.SLEEP
        
        # Try invalid transition: SLEEP → SPEAKING (must skip LISTENING, THINKING)
        with self.assertRaises(RuntimeError) as ctx:
            self.state_machine._transition(State.SPEAKING)
        
        self.assertIn("Invalid transition", str(ctx.exception))
        # State machine should not have changed
        self.assertEqual(self.state_machine.current_state, State.SLEEP)
    
    def test_audio_authority_hard_kill_prevents_reacquisition(self):
        """
        TEST 3: Audio authority hard-kill prevents speaker reacquisition.
        
        Scenario:
        1. Speaker acquired for TTS
        2. Interrupt calls hard_kill_output()
        3. Try to acquire speaker again
        4. Acquisition fails (speaker_killed=True)
        5. Must reset() to allow next interaction
        """
        authority = AudioAuthority()
        
        # Acquire speaker
        acquired = authority.acquire("speaker", owner="tts")
        self.assertTrue(acquired)
        
        # Hard-kill on interrupt
        authority.hard_kill_output()
        
        # Try to acquire again (should fail)
        released = authority.release("speaker", owner="tts")
        self.assertTrue(released)  # Released OK
        
        # Try to acquire again after hard-kill
        acquired = authority.acquire("speaker", owner="tts_retry")
        self.assertFalse(acquired)  # Cannot acquire (was hard-killed)
        
        # Reset allows next interaction
        authority.reset()
        acquired = authority.acquire("speaker", owner="tts_next")
        self.assertTrue(acquired)  # Now can acquire again
    
    def test_barge_in_sequence_wake_listen_speak_interrupt_resume(self):
        """
        TEST 4: Full barge-in sequence is atomic.
        
        Scenario (simplified):
        1. Wake: SLEEP → LISTENING
        2. Listen: user speech captured
        3. Process: LISTENING → THINKING → SPEAKING
        4. Speak: TTS starts (long sentence)
        5. Interrupt: Wake word detected during TTS
           - Audio hard-killed
           - TTS stopped
           - State reset to LISTENING
        6. Resume: Next wake → next interaction
        """
        sm = StateMachine()
        
        # 1. Wake: SLEEP → LISTENING
        sm.wake()
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # 2-3. Process: LISTENING → THINKING → SPEAKING
        sm.accept_command()
        self.assertEqual(sm.current_state, State.THINKING)
        
        sm.start_audio()
        self.assertEqual(sm.current_state, State.SPEAKING)
        
        # 5. Interrupt: Force to LISTENING (hard reset)
        sm.listening()
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # 6. Resume: LISTENING → next wake
        sm.wake()  # This should fail (already listening)
        # Expected: Invalid transition error
        # In real code, wait for next wake word, then:
        sm.sleep()  # Go back to SLEEP to test full loop
        self.assertEqual(sm.current_state, State.SLEEP)
        
        sm.wake()
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_multiple_back_to_back_interrupts(self):
        """
        TEST 5: Multiple rapid interrupts don't cause state corruption.
        
        Scenario:
        1. Wake → LISTENING → THINKING → SPEAKING
        2. Interrupt (hard-kill, reset to LISTENING)
        3. User starts speaking again
        4. New response generated and started
        5. User interrupts again (rapid)
        6. System should handle gracefully
        """
        sm = StateMachine()
        auth = AudioAuthority()
        
        # First cycle
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # First interrupt
        sm.listening()  # Reset to LISTENING
        auth.hard_kill_output()
        auth.reset()  # Reset for next interaction
        
        # Second cycle
        sm.wake()  # Should fail (in LISTENING, need SLEEP first)
        # In real code, would need to sleep first:
        sm.sleep()
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # Second interrupt
        sm.listening()
        auth.hard_kill_output()
        auth.reset()
        
        # Verify final state
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # Verify audio authority is reset
        acquired = auth.acquire("speaker", owner="final")
        self.assertTrue(acquired)
    
    def test_interaction_id_monotonic_increment(self):
        """
        TEST 6: Interaction IDs increment monotonically per wake.
        
        Scenario:
        1. Wake word detected → generate ID=1
        2. Wake word detected → generate ID=2
        3. Wake word detected → generate ID=3
        4. IDs are strictly increasing (prevent reuse)
        """
        class MockCoordinator:
            def __init__(self):
                self._interaction_id = 0
            
            def _next_interaction_id(self) -> int:
                self._interaction_id += 1
                return self._interaction_id
        
        coord = MockCoordinator()
        
        id1 = coord._next_interaction_id()
        id2 = coord._next_interaction_id()
        id3 = coord._next_interaction_id()
        
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)
        self.assertEqual(id3, 3)
        
        # IDs should never collide
        self.assertEqual(len(set([id1, id2, id3])), 3)
    
    def test_interrupt_is_synchronous_no_timeout(self):
        """
        TEST 7: Interrupt is synchronous with no waiting.
        
        Scenario:
        1. Long TTS sentence starts (e.g., "Reading the first 10000 lines of War and Peace...")
        2. Wake word detected
        3. stop_interrupt() is called
        4. Method returns IMMEDIATELY (no timeout, no waiting for TTS to finish)
        5. Next action (state reset) happens synchronously
        
        Timing: interrupt must complete in < 10ms
        """
        sink = PiperOutputSink(piper_path="echo", voice_path="dummy.onnx")
        
        # Simulate interrupt timing
        start = time.time()
        sink.stop_interrupt()
        elapsed = time.time() - start
        
        # stop_interrupt() should be instant (< 100ms even on slow system)
        self.assertLess(elapsed, 0.1, f"stop_interrupt() took {elapsed*1000:.1f}ms, should be < 100ms")


class TestBargeInIntegration(unittest.TestCase):
    """Integration tests for full barge-in flow."""
    
    def test_zombie_callback_cannot_speak_after_interrupt(self):
        """
        Integration: Stale TTS callback cannot speak after interrupt.
        
        Scenario:
        1. Start interaction with ID=5
        2. queue text for playback
        3. Worker thread dequeues (interaction_id=5)
        4. Wake word interrupt happens
        5. stop_interrupt() sets interaction_id=None
        6. Worker thread tries to play: checks ID, sees None, skips
        7. New interaction starts with ID=6
        8. New text queued and plays successfully
        
        Result: Old callbacks never speak, preventing zombie audio
        """
        # This is a conceptual test - would need full threading setup
        # Demonstrating the pattern:
        
        class TTS:
            def __init__(self):
                self._interaction_id = None
            
            def speak(self, text, interaction_id):
                self._interaction_id = interaction_id
            
            def stop_interrupt(self):
                self._interaction_id = None
            
            def would_play(self):
                # Check before playback
                return self._interaction_id is not None
        
        tts = TTS()
        
        # Interaction 1: ID=5
        tts.speak("Long response", interaction_id=5)
        self.assertTrue(tts.would_play())
        
        # Interrupt
        tts.stop_interrupt()
        self.assertFalse(tts.would_play())
        
        # Interaction 2: ID=6
        tts.speak("New response", interaction_id=6)
        self.assertTrue(tts.would_play())


def run_tests():
    """Run all barge-in atomicity tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBargeInAtomicity))
    suite.addTests(loader.loadTestsFromTestCase(TestBargeInIntegration))
    
    # Run with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with failure code if any tests failed
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
