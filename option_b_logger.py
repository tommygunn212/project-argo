#!/usr/bin/env python3
"""
Option B: Confidence Burn-In Test Harness
Logging framework for observing ARGO behavior during normal use

Records:
- Timing data (STOP latency, response duration)
- State transitions
- Deviations from expected behavior
- User observations (annoyance markers)

Read-only observation only. No code changes.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ConversationLog:
    """Single interaction record"""
    session_id: str
    timestamp: str
    user_input: str
    command_type: str  # WAKE, STOP, SLEEP, QUESTION, ACTION, UNKNOWN
    state_before: str  # SLEEP, LISTENING, THINKING, SPEAKING
    state_after: str
    response_latency_ms: float
    response_duration_ms: float
    interrupted_at_ms: Optional[float] = None  # If STOP was called
    stop_latency_ms: Optional[float] = None  # Time from STOP to audio halt
    anomaly: Optional[str] = None  # Deviation observed
    user_note: Optional[str] = None  # Bob's observation


class ConfidenceBurnInLogger:
    """Logging framework for Option B testing"""
    
    def __init__(self, log_dir: Path = None):
        if log_dir is None:
            log_dir = Path(__file__).parent / "logs" / "confidence_burn_in"
        
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Session tracking
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.log_dir / f"session_{self.session_id}.jsonl"
        
        # Setup logging
        self.logger = logging.getLogger("ConfidenceBurnIn")
        self.logger.setLevel(logging.INFO)
        
        # Log to file
        handler = logging.FileHandler(self.log_dir / f"session_{self.session_id}.log")
        handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s'
        ))
        self.logger.addHandler(handler)
    
    def log_interaction(self, log: ConversationLog) -> None:
        """Record single interaction"""
        with open(self.session_file, 'a') as f:
            f.write(json.dumps(asdict(log)) + '\n')
        
        # Also log to console
        status = "✓" if not log.anomaly else "⚠"
        self.logger.info(
            f"{status} {log.command_type:10} | "
            f"Latency: {log.response_latency_ms:6.0f}ms | "
            f"Duration: {log.response_duration_ms:6.0f}ms"
        )
        
        if log.anomaly:
            self.logger.warning(f"  ANOMALY: {log.anomaly}")
        if log.user_note:
            self.logger.info(f"  NOTE: {log.user_note}")
    
    def log_anomaly(self, description: str) -> None:
        """Record unexpected behavior"""
        self.logger.warning(f"ANOMALY: {description}")
        with open(self.log_dir / "anomalies.txt", 'a') as f:
            f.write(f"{datetime.now().isoformat()} | {description}\n")
    
    def log_tier_result(self, tier: int, description: str, passed: bool) -> None:
        """Record test tier result"""
        status = "PASS" if passed else "FAIL"
        self.logger.info(f"[TIER {tier}] {description}: {status}")
        with open(self.log_dir / "tier_results.txt", 'a') as f:
            f.write(f"{datetime.now().isoformat()} | TIER {tier} | {status} | {description}\n")


# Module-level instance
_logger: Optional[ConfidenceBurnInLogger] = None


def get_logger() -> ConfidenceBurnInLogger:
    """Get or create logger"""
    global _logger
    if _logger is None:
        _logger = ConfidenceBurnInLogger()
    return _logger


def log_interaction(
    user_input: str,
    command_type: str,
    state_before: str,
    state_after: str,
    response_latency_ms: float,
    response_duration_ms: float,
    interrupted_at_ms: Optional[float] = None,
    stop_latency_ms: Optional[float] = None,
    anomaly: Optional[str] = None,
    user_note: Optional[str] = None
) -> None:
    """Log interaction (simplified API)"""
    logger = get_logger()
    log = ConversationLog(
        session_id=logger.session_id,
        timestamp=datetime.now().isoformat(),
        user_input=user_input,
        command_type=command_type,
        state_before=state_before,
        state_after=state_after,
        response_latency_ms=response_latency_ms,
        response_duration_ms=response_duration_ms,
        interrupted_at_ms=interrupted_at_ms,
        stop_latency_ms=stop_latency_ms,
        anomaly=anomaly,
        user_note=user_note
    )
    logger.log_interaction(log)


if __name__ == "__main__":
    print("Confidence Burn-In Logging Framework Ready")
    print("=" * 70)
    
    logger = get_logger()
    print(f"Session ID: {logger.session_id}")
    print(f"Log directory: {logger.log_dir}")
    print(f"Files created:")
    print(f"  - {logger.session_file.name} (interactions)")
    print(f"  - session_{logger.session_id}.log (detailed)")
    print(f"  - anomalies.txt (accumulated)")
    print(f"  - tier_results.txt (accumulated)")
    print("\nReady for Option B testing.")
