"""This PC: hardware, health, volume and the gaming/editing profile.
"""

from __future__ import annotations

from core.realtime_tools._base import capability, logger

__all__ = [
    "pc_specs",
    "drive_space",
    "system_status",
    "diagnostics",
    "volume_set",
    "volume_status",
    "pc_profile_set",
    "pc_profile_status",
]


def _memory() -> tuple:
    try:
        from system_health import get_memory_info

        return get_memory_info()
    except Exception:
        logger.exception("[Tools] memory info unavailable")
        return None, None


@capability
def pc_specs() -> dict:
    """Motherboard, BIOS, CPU, RAM and graphics for this machine."""
    from system_profile import get_system_profile, get_gpu_profile

    p = get_system_profile() or {}
    gpus = get_gpu_profile() or []
    total_gb, used_pct = _memory()
    return {
        "ok": True,
        "motherboard": p.get("motherboard") or p.get("motherboard_product"),
        "motherboard_maker": p.get("motherboard_maker"),
        "bios_version": p.get("bios_version"),
        "cpu": p.get("cpu"),
        "cpu_cores": p.get("cpu_cores"),
        "cpu_threads": p.get("cpu_threads"),
        "cpu_max_mhz": p.get("cpu_max_mhz"),
        "memory_total_gb": total_gb,
        "memory_used_percent": used_pct,
        "memory_speed_mhz": p.get("memory_speed_mhz"),
        "memory_modules": p.get("memory_modules"),
        "graphics": [
            {"name": g.get("name"), "driver": g.get("driver_version")} for g in gpus
        ],
        "os": p.get("os"),
    }


@capability
def drive_space() -> dict:
    """Free and used space for every drive."""
    from system_health import get_disk_info

    return {"ok": True, "drives": get_disk_info() or {}}


@capability
def system_status() -> dict:
    """Live health: memory, temperatures, overall status."""
    from system_health import get_system_health, get_temperatures

    total_gb, used_pct = _memory()
    return {
        "ok": True,
        "health": get_system_health() or {},
        "temperatures_c": get_temperatures() or {},
        "memory_total_gb": total_gb,
        "memory_used_percent": used_pct,
    }


@capability
def diagnostics() -> dict:
    """Run ARGO's own self-diagnostics and report component health."""
    from core.self_diagnostics import run_diagnostics

    return {"ok": True, "report": run_diagnostics() or {}}


@capability
def volume_set(percent: int) -> dict:
    from core.system_volume import set_volume_percent

    pct = max(0, min(100, int(percent)))
    ok, message, level, _prev, muted = set_volume_percent(pct)
    return {"ok": bool(ok), "volume_percent": level, "muted": muted, "message": message}


@capability
def volume_status() -> dict:
    from core.system_volume import get_status

    level, muted = get_status()
    return {"ok": True, "volume_percent": level, "muted": muted}


@capability
def pc_profile_set(mode: str) -> dict:
    """Switch the PC between the "gaming" and "editing" profiles - power
    plan, display refresh rate, and any configured background apps to close.
    """
    from core.pc_profile import apply_profile

    return apply_profile(mode)


@capability
def pc_profile_status() -> dict:
    """Current power plan, display refresh rate, and which PC profile was
    applied last."""
    from core.pc_profile import get_status

    return get_status()
