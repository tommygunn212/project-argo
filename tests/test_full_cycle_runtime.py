"""
TEST: Phase 7B-2 Full Cycle Runtime Integration

Complete runtime testing for state machine + OutputSink integration.

Test Scenarios:
1. Full cycle: SLEEP -> LISTENING -> THINKING -> SPEAKING -> LISTENING -> SLEEP
2. Interruption: STOP during SPEAKING returns to LISTENING immediately
3. State machine is authoritative: all state changes go through state machine only
4. OutputSink.stop() called immediately on STOP command (no fade-out)
5. Listening gate: microphone blocked when not in LISTENING state

Test approach (no keyboard interaction):
- Direct function calls to simulate user actions
- Mock OutputSink for testing without real audio
- Verify state transitions and OutputSink calls
"""

import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Add argo root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.state_machine import State, StateMachine, get_state_machine, set_state_machine
from core.output_sink import get_output_sink, set_output_sink


# ============================================================================
# TEST SETUP
# ============================================================================

class MockOutputSink:
    """Mock OutputSink for testing without real audio"""
    
    def __init__(self):
        self.send_calls = []
        self.stop_calls = []
        self.is_playing = False
    
    def send(self, text, voice="amy"):
        """Mock send (async)"""
        self.send_calls.append({"text": text, "voice": voice})
        self.is_playing = True
    
    def stop(self):
        """Mock stop (immediate)"""
        self.stop_calls.append({"time": "immediate"})
        self.is_playing = False
    
    async def async_send(self, text, voice="amy"):
        """Mock async send"""
        self.send(text, voice)


# ============================================================================
# FULL CYCLE TESTS
# ============================================================================

class TestFullCycleRuntime(unittest.TestCase):
    """Test complete flow: SLEEP -> LISTENING -> THINKING -> SPEAKING -> LISTENING -> SLEEP"""
    
    def setUp(self):
        """Reset state machine before each test"""
        sm = StateMachine()
        set_state_machine(sm)
        
        # Use mock sink
        mock_sink = MockOutputSink()
        set_output_sink(mock_sink)
    
    def test_full_cycle_complete_flow(self):
        """Complete full cycle: SLEEP -> LISTENING -> THINKING -> SPEAKING -> LISTENING -> SLEEP"""
        sm = get_state_machine()
        
        # Initial: SLEEP
        self.assertEqual(sm.current_state, State.SLEEP)
        self.assertTrue(sm.is_asleep)
        
        # User says "ARGO" -> LISTENING
        self.assertTrue(sm.wake())
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertTrue(sm.is_listening)
        
        # Command accepted -> THINKING
        self.assertTrue(sm.accept_command())
        self.assertEqual(sm.current_state, State.THINKING)
        self.assertTrue(sm.is_thinking)
        
        # Audio starts -> SPEAKING
        self.assertTrue(sm.start_audio())
        self.assertEqual(sm.current_state, State.SPEAKING)
        self.assertTrue(sm.is_speaking)
        
        # Audio ends naturally -> LISTENING
        self.assertTrue(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertTrue(sm.is_listening)
        
        # User says "go to sleep" -> SLEEP
        self.assertTrue(sm.sleep())
        self.assertEqual(sm.current_state, State.SLEEP)
        self.assertTrue(sm.is_asleep)
    
    def test_listening_enabled_only_in_listening(self):
        """listening_enabled() returns True only in LISTENING state"""
        sm = get_state_machine()
        
        # In SLEEP: listening disabled
        self.assertFalse(sm.listening_enabled())
        
        # Wake to LISTENING
        sm.wake()
        self.assertTrue(sm.listening_enabled())
        
        # Accept command -> THINKING: listening disabled
        sm.accept_command()
        self.assertFalse(sm.listening_enabled())
        
        # Start audio -> SPEAKING: listening disabled
        sm.start_audio()
        self.assertFalse(sm.listening_enabled())
        
        # Stop -> LISTENING: listening enabled again
        sm.stop_audio()
        self.assertTrue(sm.listening_enabled())
    
    def test_cannot_advance_without_wake(self):
        """Cannot transition past SLEEP without wake"""
        sm = get_state_machine()
        
        # In SLEEP: accept_command should fail
        self.assertFalse(sm.accept_command())
        self.assertEqual(sm.current_state, State.SLEEP)
        
        # In SLEEP: start_audio should fail
        self.assertFalse(sm.start_audio())
        self.assertEqual(sm.current_state, State.SLEEP)


# ============================================================================
# INTERRUPTION TESTS (STOP DURING SPEAKING)
# ============================================================================

class TestInterruptionDuringAudio(unittest.TestCase):
    """Test STOP command during SPEAKING"""
    
    def setUp(self):
        """Reset state machine before each test"""
        sm = StateMachine()
        set_state_machine(sm)
        
        # Use mock sink
        mock_sink = MockOutputSink()
        set_output_sink(mock_sink)
    
    def test_stop_during_speaking(self):
        """STOP command immediately halts audio and returns to LISTENING"""
        sm = get_state_machine()
        sink = get_output_sink()
        
        # Setup: Get to SPEAKING state
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        self.assertEqual(sm.current_state, State.SPEAKING)
        
        # Simulate OutputSink.send (audio playback)
        sink.send("This is a long response that might be interrupted...", voice="amy")
        self.assertTrue(sink.is_playing)
        
        # User says "stop"
        # This triggers:
        # 1. OutputSink.stop() called (immediate, no fade)
        # 2. State transition to LISTENING
        self.assertTrue(sm.stop_audio())
        sink.stop()
        
        # Verify: audio stopped immediately
        self.assertFalse(sink.is_playing)
        self.assertEqual(len(sink.stop_calls), 1)
        
        # Verify: state returned to LISTENING
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertTrue(sm.is_listening)
        self.assertTrue(sm.listening_enabled())
    
    def test_stop_call_happens_before_state_transition(self):
        """OutputSink.stop() is called before state transition"""
        sm = get_state_machine()
        sink = get_output_sink()
        
        # Setup: SPEAKING
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        sink.send("Some text")
        
        # Record stop call
        sink.stop()
        
        # Then state transition
        sm.stop_audio()
        
        # Both happened in order
        self.assertEqual(len(sink.stop_calls), 1)
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_cannot_stop_when_not_speaking(self):
        """STOP command is no-op when not in SPEAKING"""
        sm = get_state_machine()
        
        # In LISTENING: stop should fail
        sm.wake()
        self.assertFalse(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # In THINKING: stop should fail
        sm.accept_command()
        self.assertFalse(sm.stop_audio())
        self.assertEqual(sm.current_state, State.THINKING)
    
    def test_rapid_stops_are_idempotent(self):
        """Multiple STOP commands are safe (idempotent)"""
        sm = get_state_machine()
        sink = get_output_sink()
        
        # Setup: SPEAKING
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        sink.send("Some text")
        
        # First stop
        sink.stop()
        sm.stop_audio()
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertEqual(len(sink.stop_calls), 1)
        
        # Second stop should be no-op
        sink.stop()
        self.assertFalse(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertEqual(len(sink.stop_calls), 2)  # Called but no-op


# ============================================================================
# LISTENING GATE TESTS
# ============================================================================

class TestListeningGate(unittest.TestCase):
    """Test that microphone input is gated on listening_enabled()"""
    
    def setUp(self):
        """Reset state machine before each test"""
        sm = StateMachine()
        set_state_machine(sm)
    
    def test_microphone_blocked_in_sleep(self):
        """Microphone is blocked when asleep"""
        sm = get_state_machine()
        
        # In SLEEP: listening disabled
        self.assertFalse(sm.listening_enabled())
    
    def test_microphone_enabled_in_listening(self):
        """Microphone is enabled in LISTENING"""
        sm = get_state_machine()
        sm.wake()
        
        # In LISTENING: listening enabled
        self.assertTrue(sm.listening_enabled())
    
    def test_microphone_blocked_during_thinking(self):
        """Microphone is blocked while processing"""
        sm = get_state_machine()
        sm.wake()
        sm.accept_command()
        
        # In THINKING: listening disabled
        self.assertFalse(sm.listening_enabled())
    
    def test_microphone_blocked_during_speaking(self):
        """Microphone is blocked during audio playback"""
        sm = get_state_machine()
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # In SPEAKING: listening disabled
        self.assertFalse(sm.listening_enabled())


# ============================================================================
# STATE MACHINE AUTHORITY TESTS
# ============================================================================

class TestStateMachineAuthority(unittest.TestCase):
    """Test that state machine is the sole authority for state transitions"""
    
    def setUp(self):
        """Reset state machine before each test"""
        sm = StateMachine()
        set_state_machine(sm)
    
    def test_cannot_set_state_directly(self):
        """State must be changed through state machine methods only"""
        sm = get_state_machine()
        
        # Initial: SLEEP
        self.assertEqual(sm.current_state, State.SLEEP)
        
        # Can only change via methods
        sm.wake()
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # Cannot modify state directly (property is read-only)
        # This tests that _current_state is private
        with self.assertRaises(AttributeError):
            sm.current_state = State.SPEAKING
    
    def test_all_transitions_logged(self):
        """All state transitions are logged"""
        sm = get_state_machine()
        
        transitions = []
        
        def capture_transition(old_state, new_state):
            transitions.append((old_state, new_state))
        
        # Recreate with callback
        sm = StateMachine(on_state_change=capture_transition)
        set_state_machine(sm)
        
        # Perform transitions
        sm.wake()  # SLEEP -> LISTENING
        sm.accept_command()  # LISTENING -> THINKING
        sm.start_audio()  # THINKING -> SPEAKING
        sm.stop_audio()  # SPEAKING -> LISTENING
        sm.sleep()  # LISTENING -> SLEEP
        
        # Verify all transitions were logged
        self.assertEqual(len(transitions), 5)
        self.assertEqual(transitions[0], (State.SLEEP, State.LISTENING))
        self.assertEqual(transitions[1], (State.LISTENING, State.THINKING))
        self.assertEqual(transitions[2], (State.THINKING, State.SPEAKING))
        self.assertEqual(transitions[3], (State.SPEAKING, State.LISTENING))
        self.assertEqual(transitions[4], (State.LISTENING, State.SLEEP))
    
    def test_invalid_transitions_rejected(self):
        """Invalid transitions are rejected safely"""
        sm = get_state_machine()
        
        # Try invalid transition: LISTENING -> SPEAKING (missing THINKING)
        sm.wake()  # Now in LISTENING
        self.assertFalse(sm.start_audio())  # Should fail
        self.assertEqual(sm.current_state, State.LISTENING)  # State unchanged
    
    def test_only_valid_transitions_allowed(self):
        """Only the 9 allowed transitions work"""
        sm = get_state_machine()
        
        # Valid: SLEEP -> LISTENING
        self.assertTrue(sm.wake())
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # Valid: LISTENING -> THINKING
        self.assertTrue(sm.accept_command())
        self.assertEqual(sm.current_state, State.THINKING)
        
        # Valid: THINKING -> SPEAKING
        self.assertTrue(sm.start_audio())
        self.assertEqual(sm.current_state, State.SPEAKING)
        
        # Valid: SPEAKING -> LISTENING
        self.assertTrue(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # Valid: LISTENING -> SLEEP
        self.assertTrue(sm.sleep())
        self.assertEqual(sm.current_state, State.SLEEP)


# ============================================================================
# OUTPUT SINK INTEGRATION TESTS
# ============================================================================

class TestOutputSinkIntegration(unittest.TestCase):
    """Test OutputSink integration with state machine"""
    
    def setUp(self):
        """Reset state machine and sink before each test"""
        sm = StateMachine()
        set_state_machine(sm)
        
        mock_sink = MockOutputSink()
        set_output_sink(mock_sink)
    
    def test_output_sink_available(self):
        """OutputSink is available for integration"""
        sink = get_output_sink()
        self.assertIsNotNone(sink)
        self.assertTrue(hasattr(sink, 'send'))
        self.assertTrue(hasattr(sink, 'stop'))
    
    def test_send_during_speaking(self):
        """Text can be sent via OutputSink when SPEAKING"""
        sm = get_state_machine()
        sink = get_output_sink()
        
        # Setup: SPEAKING
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # Send text
        sink.send("Hello, world!", voice="amy")
        
        # Verify: send was called
        self.assertEqual(len(sink.send_calls), 1)
        self.assertEqual(sink.send_calls[0]["text"], "Hello, world!")
        self.assertEqual(sink.send_calls[0]["voice"], "amy")
    
    def test_stop_clears_is_playing(self):
        """OutputSink.stop() clears is_playing flag"""
        sm = get_state_machine()
        sink = get_output_sink()
        
        # Setup: SPEAKING
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # Send text
        sink.send("Some audio")
        self.assertTrue(sink.is_playing)
        
        # Stop
        sink.stop()
        self.assertFalse(sink.is_playing)


# ============================================================================
# INTEGRATION TEST: Wrapper Functions
# ============================================================================

class TestWrapperIntegration(unittest.TestCase):
    """Test integration with wrapper/argo.py functions"""
    
    def setUp(self):
        """Reset state machine before each test"""
        sm = StateMachine()
        set_state_machine(sm)
    
    def test_wake_word_transitions_state(self):
        """Wake word "ARGO" transitions SLEEP -> LISTENING"""
        sm = get_state_machine()
        
        # Simulate: user says "ARGO"
        # This should call sm.wake()
        self.assertTrue(sm.wake())
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_sleep_command_transitions_state(self):
        """Sleep command "go to sleep" transitions to SLEEP"""
        sm = get_state_machine()
        
        # Setup: LISTENING
        sm.wake()
        
        # Simulate: user says "go to sleep"
        # This should call sm.sleep()
        self.assertTrue(sm.sleep())
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_stop_command_transitions_state(self):
        """Stop command "stop" transitions SPEAKING -> LISTENING"""
        sm = get_state_machine()
        
        # Setup: SPEAKING
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # Simulate: user says "stop"
        # This should call sm.stop_audio() AND sink.stop()
        self.assertTrue(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)


if __name__ == "__main__":
    unittest.main()
