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
import os
import subprocess
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
    # Also: "let's count to five", "give me five numbers"
    COUNT_PATTERN = re.compile(r'count\s+to\s+(.+)', re.IGNORECASE)
    COUNT_ALT_PATTERNS = [
        re.compile(r"let'?s\s+count\s+to\s+(.+)", re.IGNORECASE),
        re.compile(r"give\s+me\s+(\w+)\s+numbers?", re.IGNORECASE),
    ]

    # Pattern: "set computer light(s) ..."
    LIGHT_PATTERN = re.compile(r'\bset\s+computer\s+lights?\b(.*)', re.IGNORECASE)

    COLOR_MAP = {
        "red": "FF0000",
        "green": "00FF00",
        "blue": "0000FF",
        "white": "FFFFFF",
        "purple": "8000FF",
        "pink": "FF00FF",
        "cyan": "00FFFF",
        "yellow": "FFFF00",
        "orange": "FFA500",
    }
    
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
        
        # Check lighting pattern
        if self.LIGHT_PATTERN.search(text):
            return True

        # Check count pattern (digits or spelled-out numbers)
        match = self.COUNT_PATTERN.search(text)
        if match:
            raw_target = match.group(1).strip().lower()
            raw_target = re.sub(r'[^\w\s]', '', raw_target)
            first_word = raw_target.split()[0] if raw_target.split() else ""
            # Validate it's a valid number (digit or known word)
            if first_word.isdigit() or first_word in WORD_TO_NUMBER:
                return True
        
        # Check alternate count patterns ("let's count to", "give me N numbers")
        for pattern in self.COUNT_ALT_PATTERNS:
            alt_match = pattern.search(text)
            if alt_match:
                raw_target = alt_match.group(1).strip().lower()
                raw_target = re.sub(r'[^\w\s]', '', raw_target)
                first_word = raw_target.split()[0] if raw_target.split() else ""
                if first_word.isdigit() or first_word in WORD_TO_NUMBER:
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
        # Try lighting command
        light_match = self.LIGHT_PATTERN.search(text)
        if light_match:
            try:
                return self._execute_lighting(light_match.group(1))
            except Exception as e:
                self.logger.error(f"[CommandExecutor] Lighting command failed: {e}")
                return False

        # Try count command (primary pattern)
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
        
        # Try alternate count patterns ("let's count to", "give me N numbers")
        for pattern in self.COUNT_ALT_PATTERNS:
            alt_match = pattern.search(text)
            if alt_match:
                try:
                    num_str = alt_match.group(1)
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

    def _execute_lighting(self, tail: str) -> bool:
        """
        Execute: set computer lights <color|mode|on|off>.

        Examples:
        - "set computer light red"
        - "set computer lights to blue"
        - "set computer lights rainbow mode"
        - "set computer light off"
        """
        tail = (tail or "").strip().lower()
        # Remove leading "to" if present
        if tail.startswith("to "):
            tail = tail[3:].strip()

        mode = None
        color = None

        if "off" in tail:
            mode = "off"
        elif "rainbow" in tail:
            mode = "rainbow"
        elif "breathing" in tail:
            mode = "breathing"
        elif "static" in tail:
            mode = "static"

        for name, hex_color in self.COLOR_MAP.items():
            if name in tail:
                color = hex_color
                if mode is None:
                    mode = "static"
                break

        if "on" in tail and mode is None:
            mode = "static"
            color = color or "FFFFFF"

        if mode is None:
            self.logger.warning("[CommandExecutor] Lighting command missing mode/color")
            return False

        return self._run_openrgb(mode=mode, color=color)

    def _run_openrgb(self, mode: str, color: Optional[str] = None) -> bool:
        exe = os.getenv("OPENRGB_EXE", r"C:\Program Files\OpenRGB\OpenRGB.exe")
        if not os.path.exists(exe):
            exe = "OpenRGB.exe"

        base_args = [exe, "--client", "127.0.0.1:6742", "--mode", mode]
        if color:
            base_args += ["--color", color]

        devices_env = os.getenv("OPENRGB_DEVICES", "").strip()
        devices = [d.strip() for d in devices_env.split(",") if d.strip()] if devices_env else [None]

        success = True
        for dev in devices:
            args = list(base_args)
            if dev is not None:
                args += ["--device", dev]
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            except Exception as e:
                self.logger.error(f"[CommandExecutor] OpenRGB call failed: {e}")
                success = False
                continue

            if result.returncode != 0:
                self.logger.error(
                    "[CommandExecutor] OpenRGB error: %s",
                    (result.stderr or result.stdout).strip(),
                )
                success = False
                continue

        if self.audio_sink:
            try:
                if mode == "off":
                    self.audio_sink.speak("Computer lights off.")
                elif mode == "rainbow":
                    self.audio_sink.speak("Computer lights set to rainbow.")
                elif mode == "breathing":
                    self.audio_sink.speak("Computer lights set to breathing mode.")
                else:
                    self.audio_sink.speak("Computer lights updated.")
            except Exception as e:
                self.logger.error(f"[CommandExecutor] Failed to speak OpenRGB status: {e}")

        return bool(success)
    
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
            # Check for stop/interruption flag
            if hasattr(self, 'stop_requested') and getattr(self, 'stop_requested', False):
                self.logger.info(f"[CommandExecutor] Counting interrupted at {i-1}")
                break
            # Speak the number
            num_text = str(i)
            self.logger.info(f"Argo: {num_text}")
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
