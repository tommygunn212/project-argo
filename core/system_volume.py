"""System master volume control (Windows)."""

from __future__ import annotations

import logging

from pycaw.pycaw import AudioUtilities

LOGGER = logging.getLogger("ARGO.SystemVolume")

_LAST_NONZERO_VOLUME = 20


def _get_endpoint_volume():
    device = AudioUtilities.GetSpeakers()
    return device.EndpointVolume


def _clamp(percent: int) -> int:
    return max(0, min(100, int(percent)))


def get_status() -> tuple[int, bool]:
    try:
        endpoint = _get_endpoint_volume()
        volume = int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
        muted = bool(endpoint.GetMute())
        return _clamp(volume), muted
    except Exception:
        return 0, False


def set_volume_percent(percent: int) -> tuple[bool, str, int, int, bool]:
    prev_volume, prev_muted = get_status()
    try:
        endpoint = _get_endpoint_volume()
        clamped = _clamp(percent)
        endpoint.SetMasterVolumeLevelScalar(clamped / 100.0, None)
        endpoint.SetMute(0, None)
        _update_last_nonzero(clamped)
        new_volume, new_muted = get_status()
        return True, "", prev_volume, new_volume, new_muted
    except Exception:
        return False, "System volume unavailable.", prev_volume, prev_volume, prev_muted


def adjust_volume_percent(delta: int) -> tuple[bool, str, int, int, bool]:
    prev_volume, prev_muted = get_status()
    return set_volume_percent(prev_volume + int(delta))


def mute_volume() -> tuple[bool, str, int, int, bool]:
    prev_volume, prev_muted = get_status()
    try:
        endpoint = _get_endpoint_volume()
        endpoint.SetMasterVolumeLevelScalar(0.0, None)
        endpoint.SetMute(1, None)
        new_volume, new_muted = get_status()
        return True, "", prev_volume, new_volume, new_muted
    except Exception:
        return False, "System volume unavailable.", prev_volume, prev_volume, prev_muted


def unmute_volume() -> tuple[bool, str, int, int, bool]:
    prev_volume, prev_muted = get_status()
    try:
        endpoint = _get_endpoint_volume()
        restore = _LAST_NONZERO_VOLUME if _LAST_NONZERO_VOLUME > 0 else 20
        restore = _clamp(restore)
        endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(restore / 100.0, None)
        new_volume, new_muted = get_status()
        _update_last_nonzero(new_volume)
        return True, "", prev_volume, new_volume, new_muted
    except Exception:
        return False, "System volume unavailable.", prev_volume, prev_volume, prev_muted


def _update_last_nonzero(value: int) -> None:
    global _LAST_NONZERO_VOLUME
    if value > 0:
        _LAST_NONZERO_VOLUME = value
