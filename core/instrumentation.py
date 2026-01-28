"""
Instrumentation module for ARGO.

Provides millisecond-precision event logging for atomicity verification:
- Interrupt latency tracking
- Event ordering verification
- Overlap detection
"""

import logging
import time
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


def log_event(event: str, stage: str = "", interaction_id: str = ""):
    """
    Log event with monotonic timeline metadata.

    Format: [EVT] t=<ms> id=<interaction_id> stage=<stage> event=<event> thread=<thread>

    Args:
        event: Event label/message
        stage: Optional stage name (e.g., "stt", "llm", "tts")
        interaction_id: Optional interaction id for correlation
    """
    ts = int(time.monotonic() * 1000)
    thread = threading.current_thread().name
    logger.info(
        f"[EVT] t={ts} id={interaction_id} stage={stage} event={event} thread={thread}"
    )


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
