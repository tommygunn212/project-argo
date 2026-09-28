"""Guarded wake-word detector lifecycle operations."""

from __future__ import annotations


def start_detector(detector, logger) -> None:
    _invoke(detector, "start", "started", "starting", logger)


def stop_detector(detector, logger) -> None:
    _invoke(detector, "stop", "stopped", "stopping", logger)


def pause_detector(detector, logger) -> None:
    _invoke(detector, "pause", "paused (PTT active)", "pausing", logger)


def resume_detector(detector, logger) -> None:
    _invoke(detector, "resume", "resumed", "resuming", logger)


def detector_status(detector) -> dict:
    return detector.get_status() if detector else {"available": False}


def _invoke(detector, operation: str, success: str, error_action: str, logger) -> None:
    if not detector:
        return
    try:
        getattr(detector, operation)()
        logger.debug("Wake-word detector %s", success)
    except Exception as exc:
        logger.error("Error %s wake-word detector: %s", error_action, exc)
