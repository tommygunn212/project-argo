"""
STATE MACHINE FOR ARGO (Phase 7B)

Deterministic control flow: SLEEP → LISTENING → THINKING → SPEAKING → LISTENING → SLEEP

States:
- SLEEP: Not listening, audio disabled
- LISTENING: Waiting for commands
- THINKING: Processing command (inference)
- SPEAKING: Playing audio response

Allowed Transitions (ONLY THESE):
- SLEEP → LISTENING        (wake word: "ARGO")
- LISTENING → THINKING    (command accepted)
- THINKING → SPEAKING     (audio starts)
- SPEAKING → LISTENING    (audio ends)
- ANY → SLEEP             (sleep command: "go to sleep")
- SPEAKING → LISTENING    (stop command: "stop")

Core principles:
- One state at a time (no concurrent states)
- No state leaks (clean transitions)
- All state changes logged
- Invalid transitions rejected safely
- No NLP, no personality, no UI

Commands:
1. Wake: "ARGO" (case-insensitive, exact match)
   - Active: SLEEP only
   - Action: SLEEP → LISTENING

2. Sleep: "go to sleep" (case-insensitive, exact match)
   - Active: ANY non-SLEEP state
   - Action: Stop audio, transition to SLEEP

3. Stop: "stop" (case-insensitive, exact match)
   - Active: SPEAKING only
   - Action: Stop audio, transition to LISTENING

Configuration:
- WAKE_WORD_ENABLED (default: true)
- SLEEP_WORD_ENABLED (default: true)
"""

import os
import logging
from enum import Enum
from typing import Callable, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# STATE ENUMERATION
# ============================================================================

class State(Enum):
    """Valid states for ARGO state machine."""
    SLEEP = "SLEEP"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


# ============================================================================
# CONFIGURATION FLAGS
# ============================================================================

WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "true").lower() == "true"
"""Enable wake word detection ("ARGO")."""

SLEEP_WORD_ENABLED = os.getenv("SLEEP_WORD_ENABLED", "true").lower() == "true"
"""Enable sleep word detection ("go to sleep")."""


# ============================================================================
# STATE MACHINE
# ============================================================================

class StateMachine:
    """
    Deterministic state machine for ARGO control flow.
    
    Manages transitions between SLEEP, LISTENING, THINKING, SPEAKING states.
    All state changes are logged. Invalid transitions are rejected safely.
    """
    
    def __init__(self, on_state_change: Optional[Callable] = None):
        """
        Initialize state machine.
        
        Args:
            on_state_change: Optional callback on state transition (old, new)
        """
        self._current_state = State.SLEEP
        self._on_state_change = on_state_change
        logger.info(f"StateMachine initialized: {self._current_state.value}")
    
    @property
    def current_state(self) -> State:
        """Get current state."""
        return self._current_state
    
    def _transition(self, new_state: State) -> bool:
        """
        Internal: perform state transition with validation.
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition succeeded
            
        Raises:
            RuntimeError: HARDENING STEP 5 - Fatal on invalid transitions (no silent failures)
        """
        # HARDENING STEP 5: Validate transition is allowed, raise on error (fatal)
        if not self._is_valid_transition(self._current_state, new_state):
            error_msg = f"Invalid transition: {self._current_state.value} → {new_state.value}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Perform transition
        old_state = self._current_state
        self._current_state = new_state
        
        logger.info(f"State transition: {old_state.value} -> {new_state.value}")
        
        # Notify listener
        if self._on_state_change:
            self._on_state_change(old_state, new_state)
        
        return True
    
    @staticmethod
    def _is_valid_transition(old: State, new: State) -> bool:
        """
        Check if transition is allowed.
        
        Valid transitions:
        - SLEEP → LISTENING (wake word)
        - LISTENING → THINKING (command)
        - THINKING → SPEAKING (audio starts)
        - SPEAKING → LISTENING (audio ends / stop)
        - ANY → SLEEP (sleep command)
        
        Args:
            old: Current state
            new: Target state
            
        Returns:
            True if transition allowed
        """
        # Any state can transition to SLEEP (sleep command)
        if new == State.SLEEP:
            return old != State.SLEEP
        
        # Normal state progression
        valid_transitions = {
            State.SLEEP: {State.LISTENING},          # Wake word
            State.LISTENING: {State.THINKING},       # Command accepted
            State.THINKING: {State.SPEAKING},        # Audio starts
            State.SPEAKING: {State.LISTENING},       # Audio ends / stop
        }
        
        return new in valid_transitions.get(old, set())
    
    # ========================================================================
    # PUBLIC TRANSITION METHODS
    # ========================================================================
    
    def wake(self) -> bool:
        """
        Handle wake word ("ARGO").
        
        - Active only in SLEEP state
        - Transitions to LISTENING
        
        Returns:
            True if wake succeeded, False if already awake
        """
        if not WAKE_WORD_ENABLED:
            return False
        
        if self._current_state != State.SLEEP:
            logger.debug("Wake ignored: already awake")
            return False
        
        return self._transition(State.LISTENING)
    
    def accept_command(self) -> bool:
        """
        Handle command accepted (inference starting).
        
        - Active only in LISTENING state
        - Transitions to THINKING
        
        Returns:
            True if transition succeeded, False if not listening
        """
        if self._current_state != State.LISTENING:
            logger.debug("Command accepted ignored: not in LISTENING state")
            return False
        
        return self._transition(State.THINKING)
    
    def start_audio(self) -> bool:
        """
        Handle audio playback started.
        
        - Active only in THINKING state
        - Transitions to SPEAKING
        
        Returns:
            True if transition succeeded, False if not thinking
        """
        if self._current_state != State.THINKING:
            logger.debug("Start audio ignored: not in THINKING state")
            return False
        
        return self._transition(State.SPEAKING)
    
    def stop_audio(self) -> bool:
        """
        Handle stop command ("stop") or audio ends naturally.
        
        From SPEAKING:
        - Stops audio immediately
        - Transitions to LISTENING
        
        Returns:
            True if transition succeeded, False if not speaking
        """
        if self._current_state != State.SPEAKING:
            logger.debug("Stop audio ignored: not in SPEAKING state")
            return False
        
        return self._transition(State.LISTENING)
    
    def listening(self) -> bool:
        """
        Force transition to LISTENING state.
        
        Used by barge-in to reset state after interrupt.
        Will raise RuntimeError if not in SPEAKING state (fatal on invalid transitions).
        
        Returns:
            True if transition succeeded
        """
        # HARDENING STEP 5: Use fatal transitions
        return self._transition(State.LISTENING)
    
    def sleep(self) -> bool:
        """
        Handle sleep command ("go to sleep").
        
        - Active from ANY non-SLEEP state
        - Stops audio immediately
        - Transitions to SLEEP
        - No confirmation speech
        
        Returns:
            True if sleep succeeded, False if already sleeping
        """
        if not SLEEP_WORD_ENABLED:
            return False
        
        if self._current_state == State.SLEEP:
            logger.debug("Sleep ignored: already sleeping")
            return False
        
        return self._transition(State.SLEEP)
    
    # ========================================================================
    # STATE PREDICATES
    # ========================================================================
    
    @property
    def is_asleep(self) -> bool:
        """Check if state is SLEEP."""
        return self._current_state == State.SLEEP
    
    @property
    def is_awake(self) -> bool:
        """Check if state is not SLEEP."""
        return self._current_state != State.SLEEP
    
    @property
    def is_listening(self) -> bool:
        """Check if state is LISTENING."""
        return self._current_state == State.LISTENING
    
    @property
    def is_thinking(self) -> bool:
        """Check if state is THINKING."""
        return self._current_state == State.THINKING
    
    @property
    def is_speaking(self) -> bool:
        """Check if state is SPEAKING."""
        return self._current_state == State.SPEAKING
    
    def listening_enabled(self) -> bool:
        """Check if listening is enabled (in LISTENING state)."""
        return self.is_listening


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_state_machine: Optional[StateMachine] = None
"""Global state machine instance (lazy initialization)."""


def get_state_machine() -> StateMachine:
    """
    Get or initialize the global state machine.
    
    Returns:
        StateMachine: The global instance
    """
    global _state_machine
    if _state_machine is None:
        _state_machine = StateMachine()
    return _state_machine


def set_state_machine(machine: StateMachine) -> None:
    """
    Replace the global state machine (used in testing).
    
    Args:
        machine: New StateMachine instance
    """
    global _state_machine
    _state_machine = machine
