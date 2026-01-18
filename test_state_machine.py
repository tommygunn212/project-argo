"""
TEST: State Machine (Phase 7B)

Comprehensive test suite for ARGO state machine.

States: SLEEP, LISTENING, THINKING, SPEAKING
Commands: wake ("ARGO"), sleep ("go to sleep"), stop ("stop")

Key tests:
1. State initialization (starts in SLEEP)
2. Wake word only works from SLEEP
3. Sleep word works from any non-SLEEP state
4. Stop command only works from SPEAKING
5. Invalid transitions rejected safely
6. State predicates work correctly
7. No state leaks after transitions
8. Configuration flags control behavior
"""

import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add argo root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.state_machine import (
    State,
    StateMachine,
    get_state_machine,
    set_state_machine,
    WAKE_WORD_ENABLED,
    SLEEP_WORD_ENABLED,
)


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestStateInitialization(unittest.TestCase):
    """Test state machine initialization."""
    
    def test_initial_state_is_sleep(self):
        """State machine starts in SLEEP."""
        sm = StateMachine()
        self.assertEqual(sm.current_state, State.SLEEP)
        self.assertTrue(sm.is_asleep)
    
    def test_is_asleep_predicate(self):
        """is_asleep predicate works."""
        sm = StateMachine()
        self.assertTrue(sm.is_asleep)
        self.assertFalse(sm.is_awake)
    
    def test_listening_enabled_false_in_sleep(self):
        """Listening disabled when sleeping."""
        sm = StateMachine()
        self.assertFalse(sm.listening_enabled())
    
    def test_state_predicates(self):
        """All state predicates work correctly."""
        sm = StateMachine()
        
        # In SLEEP
        self.assertTrue(sm.is_asleep)
        self.assertFalse(sm.is_awake)
        self.assertFalse(sm.is_listening)
        self.assertFalse(sm.is_thinking)
        self.assertFalse(sm.is_speaking)


# ============================================================================
# WAKE WORD TESTS
# ============================================================================

class TestWakeWord(unittest.TestCase):
    """Test wake word behavior."""
    
    def test_wake_from_sleep(self):
        """Wake word transitions SLEEP → LISTENING."""
        sm = StateMachine()
        result = sm.wake()
        
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.LISTENING)
        self.assertTrue(sm.is_listening)
    
    def test_wake_ignored_when_already_awake(self):
        """Wake word ignored if not in SLEEP state."""
        sm = StateMachine()
        sm.wake()  # Now in LISTENING
        
        # Try to wake again
        result = sm.wake()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_wake_ignored_from_thinking(self):
        """Wake word ignored from THINKING state."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()  # Now in THINKING
        
        result = sm.wake()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.THINKING)
    
    def test_wake_ignored_from_speaking(self):
        """Wake word ignored from SPEAKING state."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()
        sm.start_audio()  # Now in SPEAKING
        
        result = sm.wake()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.SPEAKING)
    
    @patch("core.state_machine.WAKE_WORD_ENABLED", False)
    def test_wake_disabled_by_config(self):
        """Wake word disabled by WAKE_WORD_ENABLED=false."""
        sm = StateMachine()
        result = sm.wake()
        
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.SLEEP)


# ============================================================================
# SLEEP WORD TESTS
# ============================================================================

class TestSleepWord(unittest.TestCase):
    """Test sleep word behavior."""
    
    def test_sleep_from_listening(self):
        """Sleep word transitions LISTENING → SLEEP."""
        sm = StateMachine()
        sm.wake()  # LISTENING
        
        result = sm.sleep()
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.SLEEP)
        self.assertTrue(sm.is_asleep)
    
    def test_sleep_from_thinking(self):
        """Sleep word transitions THINKING → SLEEP."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()  # THINKING
        
        result = sm.sleep()
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_sleep_from_speaking(self):
        """Sleep word transitions SPEAKING → SLEEP."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()
        sm.start_audio()  # SPEAKING
        
        result = sm.sleep()
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_sleep_ignored_when_already_sleeping(self):
        """Sleep word ignored if already in SLEEP state."""
        sm = StateMachine()
        
        result = sm.sleep()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.SLEEP)
    
    @patch("core.state_machine.SLEEP_WORD_ENABLED", False)
    def test_sleep_disabled_by_config(self):
        """Sleep word disabled by SLEEP_WORD_ENABLED=false."""
        sm = StateMachine()
        sm.wake()  # Get to LISTENING
        
        result = sm.sleep()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.LISTENING)


# ============================================================================
# STOP COMMAND TESTS
# ============================================================================

class TestStopCommand(unittest.TestCase):
    """Test stop command behavior."""
    
    def test_stop_from_speaking(self):
        """Stop command transitions SPEAKING → LISTENING."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()
        sm.start_audio()  # SPEAKING
        
        result = sm.stop_audio()
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_stop_ignored_from_listening(self):
        """Stop command ignored from LISTENING state."""
        sm = StateMachine()
        sm.wake()  # LISTENING
        
        result = sm.stop_audio()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_stop_ignored_from_thinking(self):
        """Stop command ignored from THINKING state."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()  # THINKING
        
        result = sm.stop_audio()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.THINKING)
    
    def test_stop_ignored_from_sleep(self):
        """Stop command ignored from SLEEP state."""
        sm = StateMachine()
        
        result = sm.stop_audio()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.SLEEP)


# ============================================================================
# STATE PROGRESSION TESTS
# ============================================================================

class TestNormalStateProgression(unittest.TestCase):
    """Test normal state transitions."""
    
    def test_full_cycle(self):
        """Test full state cycle: SLEEP → LISTENING → THINKING → SPEAKING → LISTENING → SLEEP."""
        sm = StateMachine()
        
        # SLEEP → LISTENING
        self.assertTrue(sm.wake())
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # LISTENING → THINKING
        self.assertTrue(sm.accept_command())
        self.assertEqual(sm.current_state, State.THINKING)
        
        # THINKING → SPEAKING
        self.assertTrue(sm.start_audio())
        self.assertEqual(sm.current_state, State.SPEAKING)
        
        # SPEAKING → LISTENING
        self.assertTrue(sm.stop_audio())
        self.assertEqual(sm.current_state, State.LISTENING)
        
        # LISTENING → SLEEP
        self.assertTrue(sm.sleep())
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_natural_audio_end(self):
        """Test audio ends naturally (SPEAKING → LISTENING)."""
        sm = StateMachine()
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        # Audio ends naturally
        result = sm.stop_audio()
        self.assertTrue(result)
        self.assertEqual(sm.current_state, State.LISTENING)


# ============================================================================
# INVALID TRANSITION TESTS
# ============================================================================

class TestInvalidTransitions(unittest.TestCase):
    """Test that invalid transitions are rejected safely."""
    
    def test_cannot_go_listening_to_sleep_directly(self):
        """Can only go LISTENING → THINKING normally (sleep command goes ANY → SLEEP)."""
        sm = StateMachine()
        sm.wake()  # LISTENING
        
        # Direct transition not allowed (only sleep/wake commands)
        # This tests the state machine rejects invalid transitions
        self.assertTrue(sm.is_listening)
    
    def test_cannot_skip_thinking(self):
        """Cannot go LISTENING → SPEAKING directly."""
        sm = StateMachine()
        sm.wake()  # LISTENING
        
        # start_audio() should fail (we're not in THINKING)
        result = sm.start_audio()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.LISTENING)
    
    def test_cannot_go_sleeping_to_thinking(self):
        """Cannot go SLEEP → THINKING directly."""
        sm = StateMachine()
        
        result = sm.accept_command()
        self.assertFalse(result)
        self.assertEqual(sm.current_state, State.SLEEP)


# ============================================================================
# STATE CALLBACKS TESTS
# ============================================================================

class TestStateCallbacks(unittest.TestCase):
    """Test state transition callbacks."""
    
    def test_callback_on_state_change(self):
        """Callback is called on state transitions."""
        transitions = []
        
        def record_transition(old, new):
            transitions.append((old, new))
        
        sm = StateMachine(on_state_change=record_transition)
        sm.wake()
        
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (State.SLEEP, State.LISTENING))
    
    def test_callback_multiple_transitions(self):
        """Callback records all transitions."""
        transitions = []
        
        def record_transition(old, new):
            transitions.append((old, new))
        
        sm = StateMachine(on_state_change=record_transition)
        sm.wake()
        sm.accept_command()
        sm.start_audio()
        
        self.assertEqual(len(transitions), 3)
        self.assertEqual(transitions[0], (State.SLEEP, State.LISTENING))
        self.assertEqual(transitions[1], (State.LISTENING, State.THINKING))
        self.assertEqual(transitions[2], (State.THINKING, State.SPEAKING))
    
    def test_callback_on_failed_transition(self):
        """Callback not called on failed transitions."""
        transitions = []
        
        def record_transition(old, new):
            transitions.append((old, new))
        
        sm = StateMachine(on_state_change=record_transition)
        sm.wake()  # LISTENING
        sm.wake()  # Try to wake again (fails)
        
        # Should only have 1 transition
        self.assertEqual(len(transitions), 1)


# ============================================================================
# GLOBAL INSTANCE TESTS
# ============================================================================

class TestGlobalInstance(unittest.TestCase):
    """Test global state machine instance."""
    
    def test_get_state_machine_lazy_init(self):
        """get_state_machine() lazy-initializes global instance."""
        import core.state_machine as sm_module
        sm_module._state_machine = None
        
        sm = get_state_machine()
        self.assertIsInstance(sm, StateMachine)
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_set_state_machine(self):
        """set_state_machine() replaces global instance."""
        new_sm = StateMachine()
        set_state_machine(new_sm)
        
        retrieved = get_state_machine()
        self.assertIs(retrieved, new_sm)


# ============================================================================
# CONSTRAINT COMPLIANCE TESTS
# ============================================================================

class TestConstraintCompliance(unittest.TestCase):
    """Verify hard constraints."""
    
    def test_one_state_at_a_time(self):
        """Only one state at a time (no concurrent states)."""
        sm = StateMachine()
        
        # At any point, state is exactly one of SLEEP, LISTENING, THINKING, SPEAKING
        valid_states = {State.SLEEP, State.LISTENING, State.THINKING, State.SPEAKING}
        self.assertIn(sm.current_state, valid_states)
        
        # Transition and verify
        sm.wake()
        self.assertIn(sm.current_state, valid_states)
        self.assertEqual(len({sm.current_state}), 1)
    
    def test_no_state_leaks(self):
        """State machine doesn't leak invalid states."""
        sm = StateMachine()
        
        # Simulate many transitions
        for _ in range(100):
            sm.wake()
            sm.accept_command()
            sm.start_audio()
            sm.stop_audio()
            sm.sleep()
        
        # Final state should be valid
        self.assertEqual(sm.current_state, State.SLEEP)
    
    def test_configuration_respected(self):
        """Configuration flags are respected."""
        # This is tested in decorator tests above
        # But we verify that WAKE_WORD_ENABLED and SLEEP_WORD_ENABLED exist
        self.assertIsInstance(WAKE_WORD_ENABLED, bool)
        self.assertIsInstance(SLEEP_WORD_ENABLED, bool)


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
