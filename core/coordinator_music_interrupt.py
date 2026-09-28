"""Interrupt polling and audio cleanup for coordinator music playback."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MusicInterruptDependencies:
    is_playing: Callable[[], bool]
    check_for_interrupt: Callable[[], bool]
    stop_music: Callable[[], None]
    release_audio: Callable[[str], None]
    sleep: Callable[[float], None]
    logger: Any


def monitor_music_interrupt(
    dependencies: MusicInterruptDependencies,
    *,
    poll_interval_seconds: float = 0.2,
) -> None:
    """Stop playing music on user interrupt and always release its ownership."""

    try:
        dependencies.logger.info("[Music] Monitoring for interrupt...")
        while dependencies.is_playing():
            try:
                if dependencies.check_for_interrupt():
                    dependencies.logger.warning(
                        "[Music] User interrupted! Stopping music..."
                    )
                    dependencies.stop_music()
                    break
            except Exception as exc:
                dependencies.logger.debug(
                    f"[Music] Interrupt check failed: {exc}"
                )
            dependencies.sleep(poll_interval_seconds)
    except Exception as exc:
        dependencies.logger.error(f"[Music] Monitor error: {exc}")
    finally:
        try:
            dependencies.release_audio("MUSIC")
        except Exception:
            pass
