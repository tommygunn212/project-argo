#!/usr/bin/env python3
"""
Phase 7B-3: Command Parser Layer
Deterministic, unambiguous command classification with strict priority ordering

Classification: WAKE, SLEEP, STOP, ACTION, QUESTION, UNKNOWN
Priority Order: STOP > SLEEP > WAKE > ACTION > QUESTION
Matching Strategy: Exact/near-exact only, no fuzzy semantics
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Tuple, Optional

logger = logging.getLogger("COMMAND_PARSER")


class CommandType(Enum):
    """Command classification types - mutually exclusive"""
    STOP = "STOP"
    SLEEP = "SLEEP"
    WAKE = "WAKE"
    ACTION = "ACTION"
    QUESTION = "QUESTION"
    UNKNOWN = "UNKNOWN"


@dataclass
class ParsedCommand:
    """Result of command classification"""
    command_type: CommandType
    original_text: str
    cleaned_text: str  # Text with control words stripped
    confidence: float  # 0.0-1.0, 1.0 for exact matches
    matched_pattern: Optional[str] = None
    state_required: Optional[str] = None  # State required for this command to be valid
    
    def __repr__(self) -> str:
        return (
            f"ParsedCommand(type={self.command_type.value}, "
            f"confidence={self.confidence:.2f}, "
            f"matched={self.matched_pattern})"
        )


class CommandClassifier:
    """Deterministic command classification layer"""
    
    # EXACT MATCH PATTERNS - Control commands (highest priority)
    # These NEVER go to LLM and must be unambiguous
    
    STOP_PATTERNS = [
        # Single word, isolated
        r'^\s*stop\s*[.!?]*$',
        # Within sentence boundary (not part of larger word)
        r'^\s*stop\s+',
        r'\s+stop\s*[.!?]*$',
    ]
    
    SLEEP_PATTERNS = [
        # Must start with "go" to avoid matching just "argo"
        # Standard phrase
        r'^\s*go\s+to\s+sleep\b',
        # Variant: "go to sleep"
        r'^\s*go\s+sleep\b',
        # With ARGO prefix but ARGO before "go"
        r'^\s*argo\s+go\s+to\s+sleep\b',
        r'^\s*argo\s+go\s+sleep\b',
        # "go to sleep" anywhere with word boundary
        r'\bgo\s+to\s+sleep\b',
        r'\bgo\s+sleep\b',
    ]
    
    WAKE_PATTERNS = [
        # Single word ARGO (case-insensitive)
        r'^\s*argo\s*[.!?]*$',
        # ARGO at start of sentence
        r'^\s*argo\s+',
    ]
    
    # Content classification (lower priority)
    QUESTION_KEYWORDS = {
        'how', 'what', 'when', 'where', 'why', 'which', 'who', 'whom',
        'can', 'could', 'should', 'would', 'will', 'do', 'does', 'did',
        'is', 'are', 'was', 'were', 'been', 'be',
    }
    
    ACTION_KEYWORDS = {
        'play', 'stop', 'pause', 'resume', 'next', 'previous', 'skip',
        'turn on', 'turn off', 'set', 'adjust', 'change', 'show', 'display',
        'open', 'close', 'start', 'begin', 'end', 'quit', 'exit',
    }
    
    def __init__(self, state_machine=None):
        """
        Initialize command classifier
        
        Args:
            state_machine: Optional StateMachine instance for state-aware parsing
        """
        self.state_machine = state_machine
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficiency"""
        self.stop_regexes = [re.compile(p, re.IGNORECASE) for p in self.STOP_PATTERNS]
        self.sleep_regexes = [re.compile(p, re.IGNORECASE) for p in self.SLEEP_PATTERNS]
        self.wake_regexes = [re.compile(p, re.IGNORECASE) for p in self.WAKE_PATTERNS]
    
    def parse(self, text: str) -> ParsedCommand:
        """
        Classify input text into exactly one command type
        
        Priority order (enforced strictly):
        1. STOP - highest priority, never goes to LLM
        2. SLEEP - never goes to LLM
        3. WAKE - only valid in SLEEP state
        4. ACTION - content-based, goes to LLM for execution
        5. QUESTION - content-based, goes to LLM
        6. UNKNOWN - no classification
        
        Args:
            text: Raw input text (may be partial transcript)
            
        Returns:
            ParsedCommand with type, cleaned_text, and confidence
        """
        
        text = text.strip()
        if not text:
            return ParsedCommand(
                command_type=CommandType.UNKNOWN,
                original_text=text,
                cleaned_text=text,
                confidence=0.0
            )
        
        # PRIORITY 1: STOP (highest priority)
        result = self._check_stop(text)
        if result:
            return result
        
        # PRIORITY 2: SLEEP
        result = self._check_sleep(text)
        if result:
            return result
        
        # PRIORITY 3: WAKE
        result = self._check_wake(text)
        if result:
            return result
        
        # PRIORITY 4 & 5: Content classification
        result = self._classify_content(text)
        return result
    
    def _check_stop(self, text: str) -> Optional[ParsedCommand]:
        """
        Check for STOP command
        
        Must be exact match: "stop" as isolated word or sentence boundary
        Returns None if not matched (so priority chain continues)
        """
        for regex in self.stop_regexes:
            if regex.search(text):
                # Remove the word "stop" from text
                cleaned = re.sub(r'\bstop\b', '', text, flags=re.IGNORECASE).strip()
                return ParsedCommand(
                    command_type=CommandType.STOP,
                    original_text=text,
                    cleaned_text=cleaned,
                    confidence=1.0,
                    matched_pattern="STOP",
                    state_required=None  # Works in any state
                )
        
        return None
    
    def _check_sleep(self, text: str) -> Optional[ParsedCommand]:
        """
        Check for SLEEP command
        
        Must be: "go to sleep" or "go sleep"
        Returns None if not matched (priority chain continues)
        """
        for regex in self.sleep_regexes:
            if regex.search(text):
                # Remove "go to sleep" / "go sleep" / "argo" from text
                cleaned = text
                cleaned = re.sub(r'\bargo\b', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\bgo\s+to\s+sleep\b', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\bgo\s+sleep\b', '', cleaned, flags=re.IGNORECASE)
                cleaned = cleaned.strip()
                
                return ParsedCommand(
                    command_type=CommandType.SLEEP,
                    original_text=text,
                    cleaned_text=cleaned,
                    confidence=1.0,
                    matched_pattern="SLEEP",
                    state_required=None  # Works in any state
                )
        
        return None
    
    def _check_wake(self, text: str) -> Optional[ParsedCommand]:
        """
        Check for WAKE command
        
        Must be: "ARGO" (isolated or at start)
        Valid only if state_machine exists AND in SLEEP state
        Returns None if not matched or state invalid
        """
        for regex in self.wake_regexes:
            if regex.search(text):
                # Check state constraint
                if self.state_machine is not None:
                    if not self.state_machine.is_asleep:
                        # State constraint not met - not a valid WAKE command now
                        # This gets reclassified as content
                        return None
                
                # Remove "ARGO" from text (both patterns)
                cleaned = re.sub(r'^\s*argo\s+', '', text, flags=re.IGNORECASE)
                cleaned = re.sub(r'^\s*argo\s*[.!?]*$', '', cleaned, flags=re.IGNORECASE)
                cleaned = cleaned.strip()
                
                return ParsedCommand(
                    command_type=CommandType.WAKE,
                    original_text=text,
                    cleaned_text=cleaned,
                    confidence=1.0,
                    matched_pattern="WAKE",
                    state_required="SLEEP"
                )
        
        return None
    
    def _classify_content(self, text: str) -> ParsedCommand:
        """
        Classify content-based commands (ACTION or QUESTION)
        
        These are lower priority and CAN reach the LLM
        """
        
        # Check if it looks like a question
        if self._is_question(text):
            return ParsedCommand(
                command_type=CommandType.QUESTION,
                original_text=text,
                cleaned_text=text,
                confidence=0.85,
                matched_pattern="QUESTION_KEYWORD"
            )
        
        # Check if it looks like an action
        if self._is_action(text):
            return ParsedCommand(
                command_type=CommandType.ACTION,
                original_text=text,
                cleaned_text=text,
                confidence=0.70,
                matched_pattern="ACTION_KEYWORD"
            )
        
        # Default: unknown
        return ParsedCommand(
            command_type=CommandType.UNKNOWN,
            original_text=text,
            cleaned_text=text,
            confidence=0.0,
            matched_pattern=None
        )
    
    def _is_question(self, text: str) -> bool:
        """
        Detect question-like input
        
        Uses keyword detection, not semantic analysis
        Checks for question words at start or common question patterns
        """
        lower = text.lower()
        
        # Ends with question mark
        if text.rstrip().endswith('?'):
            return True
        
        # Starts with question keyword
        first_word = lower.split()[0].rstrip('.,!?') if lower.split() else ''
        if first_word in self.QUESTION_KEYWORDS:
            return True
        
        # Contains "can you", "could you", "would you", "will you"
        if any(phrase in lower for phrase in ['can you', 'could you', 'would you', 'will you']):
            return True
        
        return False
    
    def _is_action(self, text: str) -> bool:
        """
        Detect action-like input
        
        Action: direct imperative commands (play, stop, etc.)
        Uses keyword detection only
        """
        lower = text.lower()
        
        # Check for action keywords at start
        first_word = lower.split()[0].rstrip('.,!?') if lower.split() else ''
        if first_word in self.ACTION_KEYWORDS:
            return True
        
        # Check for common action phrases
        for phrase in self.ACTION_KEYWORDS:
            if phrase in lower:
                return True
        
        return False
    
    def is_control_command(self, command_type: CommandType) -> bool:
        """Check if a command type is a control command (never goes to LLM)"""
        return command_type in (CommandType.STOP, CommandType.SLEEP, CommandType.WAKE)
    
    def is_content_command(self, command_type: CommandType) -> bool:
        """Check if a command type is content (can reach LLM)"""
        return command_type in (CommandType.ACTION, CommandType.QUESTION)
    
    def should_block_input(self, command_type: CommandType, is_listening: bool) -> bool:
        """
        Determine if input should be blocked based on state/command type
        
        STOP: Never blocks (always execute immediately)
        SLEEP: Block if not listening
        Other commands: Allow if listening
        """
        if command_type == CommandType.STOP:
            return False
        
        if command_type == CommandType.SLEEP:
            return False
        
        if not is_listening:
            return True
        
        return False

    def process_wake_word_event(self, wake_word_request: 'WakeWordRequest') -> None:
        """
        Process a wake-word detection event.
        
        Called by the wake-word detector when "ARGO" is recognized.
        Respects all state machine rules:
        - If SLEEP: transition to LISTENING (system wakes up)
        - If LISTENING: transition to THINKING (hands-free command)
        - Ignored during SPEAKING/THINKING
        - Ignored during PTT (paused by argo.py)
        - PTT always overrides wake-word
        - STOP always overrides wake-word
        
        Args:
            wake_word_request: WakeWordRequest object with confidence, timestamp, source
        
        Note:
        - This method does NOT force state machine transitions
        - It sends a "request" that the state machine can accept or reject
        - The state machine has final authority
        """
        if not self.state_machine:
            return  # State machine not available; silently ignore
        
        current_state = self.state_machine.current_state
        
        # Rule 1: Ignore if SPEAKING (audio playback active)
        if current_state == "SPEAKING":
            logger.debug(f"Wake-word ignored: in SPEAKING state (audio playing)")
            return
        
        # Rule 2: Ignore if THINKING (LLM processing)
        if current_state == "THINKING":
            logger.debug(f"Wake-word ignored: in THINKING state (LLM processing)")
            return
        
        # Rule 3: Handle SLEEP state - wake up
        if current_state == "SLEEP":
            logger.info(f"Wake-word detected in SLEEP state: 'ARGO' (confidence={wake_word_request.confidence:.2f})")
            try:
                if self.state_machine.wake():
                    logger.debug("Wake-word event accepted: transition to LISTENING")
                else:
                    logger.debug("Wake-word event rejected: state machine declined wake transition")
            except Exception as e:
                logger.error(f"Error processing wake-word event: {e}")
            return
        
        # Rule 4: Handle LISTENING state - process command
        if current_state == "LISTENING":
            logger.info(f"Wake-word processed: 'ARGO' (confidence={wake_word_request.confidence:.2f}, state={current_state})")
            try:
                # Request the state machine to transition to THINKING
                # (never force; let state machine decide)
                if self.state_machine.accept_command():
                    logger.debug("Wake-word event accepted: transition to THINKING")
                else:
                    logger.debug("Wake-word event rejected: state machine declined transition")
            except Exception as e:
                logger.error(f"Error processing wake-word event: {e}")
            return
        
        # Rule 5: Any other state - ignore (shouldn't happen)
        logger.debug(f"Wake-word ignored: in {current_state} state (not SLEEP or LISTENING)")


# Module-level API
_classifier: Optional[CommandClassifier] = None


def get_classifier(state_machine=None) -> CommandClassifier:
    """Get or create command classifier"""
    global _classifier
    if _classifier is None:
        _classifier = CommandClassifier(state_machine=state_machine)
    return _classifier


def set_classifier(classifier: CommandClassifier) -> None:
    """Set global classifier (for testing)"""
    global _classifier
    _classifier = classifier


def parse(text: str) -> ParsedCommand:
    """Parse text using module-level classifier"""
    classifier = get_classifier()
    return classifier.parse(text)


if __name__ == "__main__":
    # CLI test
    import sys
    
    print("Phase 7B-3: Command Parser Test")
    print("=" * 70)
    
    classifier = CommandClassifier()
    
    test_cases = [
        "stop",
        "STOP",
        "go to sleep",
        "Go To Sleep",
        "argo",
        "ARGO",
        "argo how do I make eggs",
        "how do I make eggs",
        "can you play music",
        "stop talking and tell me a joke",
        "argo go to sleep now",
        "stop stop stop",
        "wake up",
        "play music",
        "hello",
    ]
    
    for text in test_cases:
        result = classifier.parse(text)
        print(f"\n'{text}'")
        print(f"  → {result.command_type.value} (conf={result.confidence:.2f})")
        if result.cleaned_text != result.original_text:
            print(f"  → Cleaned: '{result.cleaned_text}'")
