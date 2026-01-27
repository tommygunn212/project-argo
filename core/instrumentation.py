"""
Instrumentation module for ARGO.

Provides millisecond-precision event logging for atomicity verification:
- Interrupt latency tracking
- Event ordering verification
- Overlap detection
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def log_event(message: str):
    """
    Log event with millisecond-precision timestamp.
    
    Format: [HH:MM:SS.mmm] MESSAGE
    
    Args:
        message: Event message to log
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    logger.info(f"[{timestamp}] {message}")


def log_latency(stage: str, duration_ms=None):
    """
    Log latency checkpoint with optional duration.
    
    Args:
        stage: Stage name (e.g., "wake_detected", "recording_start")
        duration_ms: Optional duration in milliseconds
    """
    if duration_ms is not None:
        logger.info(f"[LATENCY] {stage}: {duration_ms:.2f}ms")
    else:
        logger.info(f"[LATENCY] {stage}")
