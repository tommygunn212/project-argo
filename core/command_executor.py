"""
Command Executor Module

Responsibility: Execute procedural commands directly (bypass LLM).

Examples:
- "count to 5" → Execute counting with timed output
- "repeat after me ..." → Execute echo command
- Future: timers, alarms, etc.

Does NOT:
- Modify intent parsing (that's IntentParser's job)
- Access database (no state persistence)
- Manage flow control (Coordinator handles that)
- Call ResponseGenerator (these are direct execution)

Design:
- Detect patterns AFTER intent is classified
- Patterns are simple regex (count to N, repeat after X, etc.)
- Execution uses existing audio infrastructure (PiperOutputSink)
- Returns success/failure boolean
- Coordinator decides what to do with result
"""

import logging
import re
import asyncio
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Word-to-number mapping for spoken numbers
WORD_TO_NUMBER = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
    'hundred': 100,
}


class CommandExecutor:
    """
    Execute procedural commands directly (bypass LLM).
    
    Design:
    - Check if text matches known patterns
    - If match: execute directly, return True
    - If no match: return False (Coordinator should use LLM)
    - Execution is synchronous (blocking for now)
    - Uses existing audio sink for output
    """
    
    # Pattern: "count to N" - supports digits OR spelled-out numbers
    # Matches: "count to 5", "count to five", "count to ten", "can you count to five?"
    COUNT_PATTERN = re.compile(r'count\s+to\s+(\d+|\w+)', re.IGNORECASE)
    
    def __init__(self, audio_sink=None):
        """
        Initialize CommandExecutor.
        
        Args:
            audio_sink: OutputSink instance for speaking (PiperOutputSink)
                       If None, commands are logged but not spoken
        """
        self.audio_sink = audio_sink
        self.logger = logger
    
    def can_execute(self, text: str) -> bool:
        """
        Check if text matches any known command pattern.
        
        Args:
            text: User input text
            
        Returns:
            True if matches a known pattern, False otherwise
        """
        if not text:
            return False
        
        # Check count pattern (digits or spelled-out numbers)
        match = self.COUNT_PATTERN.search(text)
        if match:
            num_str = match.group(1).lower()
            # Validate it's a valid number (digit or known word)
            if num_str.isdigit() or num_str in WORD_TO_NUMBER:
                return True
        
        # Future patterns go here
        
        return False
    
    def _parse_number(self, num_str: str) -> Optional[int]:
        """
        Parse a number from string (digit or spelled-out word).
        
        Args:
            num_str: Number string like "5" or "five"
            
        Returns:
            Integer value, or None if not parseable
        """
        num_str = num_str.lower().strip()
        
        # Try digit first
        if num_str.isdigit():
            return int(num_str)
        
        # Try word lookup
        if num_str in WORD_TO_NUMBER:
            return WORD_TO_NUMBER[num_str]
        
        return None
    
    def execute(self, text: str) -> bool:
        """
        Execute command if pattern matches.
        
        Args:
            text: User input text
            
        Returns:
            True if executed successfully, False if no pattern matched or error
        """
        # Try count command
        count_match = self.COUNT_PATTERN.search(text)
        if count_match:
            try:
                num_str = count_match.group(1)
                count_to = self._parse_number(num_str)
                if count_to is None:
                    self.logger.warning(f"[CommandExecutor] Could not parse number: '{num_str}'")
                    return False
                self._execute_count(count_to)
                return True
            except Exception as e:
                self.logger.error(f"[CommandExecutor] Count command failed: {e}")
                return False
        
        return False
    
    def _execute_count(self, count_to: int) -> None:
        """
        Execute: count from 1 to count_to.
        
        Behavior:
        - Speak each number (1, 2, 3, ...)
        - 1 second delay between numbers
        - Uses existing PiperOutputSink for audio
        - Blocks until complete
        
        Args:
            count_to: Number to count to
        """
        if count_to < 1:
            self.logger.warning(f"[CommandExecutor] Invalid count: {count_to}")
            return
        
        # Cap at reasonable limit (don't count to 1000)
        count_to = min(count_to, 100)
        
        self.logger.info(f"[CommandExecutor] Counting to {count_to}")
        
        for i in range(1, count_to + 1):
            # Speak the number
            num_text = str(i)
            
            self.logger.info(f"[CommandExecutor] Counting: {num_text}")
            
            if self.audio_sink:
                try:
                    # Speak number using existing sink
                    self.audio_sink.speak(num_text)
                except Exception as e:
                    self.logger.error(f"[CommandExecutor] Failed to speak number {num_text}: {e}")
            
            # Delay between numbers (except after last)
            if i < count_to:
                time.sleep(1.0)  # 1 second delay
        
        self.logger.info(f"[CommandExecutor] Counting complete (1 to {count_to})")
