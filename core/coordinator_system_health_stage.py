"""Deterministic system-health stage for the legacy coordinator."""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from core.intent_parser import IntentType
from system_health import (
    get_disk_info,
    get_system_full_report,
    get_system_health,
    get_temperature_health,
)
from system_profile import get_gpu_profile, get_system_profile


def dispatch_system_health_stage(
    coordinator: Any,
    intent: Any,
    mark_output: Callable[[], None],
    finalize_watchdog: Callable[[], None],
) -> bool:
    """Handle SYSTEM_HEALTH without entering procedural or LLM routing."""
    if intent.intent_type == IntentType.SYSTEM_HEALTH:
        coordinator.logger.info(f"[Iteration {coordinator.interaction_count}] System health command detected")
        subintent = getattr(intent, "subintent", None)
        raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
        bypass_llm = False
        if "drive" in raw_text_lower or "disk" in raw_text_lower:
            bypass_llm = True
            if subintent is None:
                subintent = "disk"
        if bypass_llm:
            coordinator.logger.info("[SYSTEM] Disk query detected; bypassing LLM")
        if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
            disks = get_disk_info()
            if not disks:
                response_text = "Hardware information unavailable."
            else:
                drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
                if not drive_match:
                    drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
                if drive_match:
                    letter = drive_match.group(1).upper()
                    key = f"{letter}:"
                    info = disks.get(key) or disks.get(letter)
                    if info:
                        response_text = (
                            f"{letter} drive is {info['percent']} percent full, "
                            f"with {info['free_gb']} gigabytes free."
                        )
                    else:
                        response_text = "Hardware information unavailable."
                elif "fullest" in raw_text_lower or "most used" in raw_text_lower:
                    disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                    response_text = f"{disk} is the fullest drive at {info['percent']} percent used."
                elif "most free" in raw_text_lower or "most space" in raw_text_lower:
                    disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                    response_text = f"{disk} has the most free space at {info['free_gb']} gigabytes free."
                else:
                    total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
                    response_text = f"You have {total_free} gigabytes free across {len(disks)} drives."
        elif subintent == "full":
            report = get_system_full_report()
            response_text = coordinator._format_system_full_report(report)
        elif subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
            profile = get_system_profile()
            gpus = get_gpu_profile()
            wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
            if subintent == "memory":
                ram_gb = profile.get("ram_gb") if profile else None
                if wants_specs and profile:
                    speed = profile.get("memory_speed_mhz")
                    modules = profile.get("memory_modules")
                    extra = []
                    if speed:
                        extra.append(f"{speed}MHz")
                    if modules:
                        extra.append(f"{modules} modules")
                    extra_text = f" ({', '.join(extra)})" if extra else ""
                    response_text = f"Your system has {ram_gb} gigabytes of memory{extra_text}."
                    coordinator._safe_speak(response_text, interaction_id=coordinator.interaction_id)
                    mark_output()
                    coordinator._last_utterance_time = time.time()
                    coordinator.current_probe.mark("llm_end")
                    coordinator.current_probe.mark("tts_start")
                    coordinator.current_probe.mark("tts_end")
                    coordinator.current_probe.log_summary()
                    coordinator.latency_stats.add_probe(coordinator.current_probe)
                    finalize_watchdog()
                    return True
                response_text = (
                    f"Your system has {ram_gb} gigabytes of memory."
                    if ram_gb is not None
                    else "Hardware information unavailable."
                )
            elif subintent == "cpu":
                cpu_name = profile.get("cpu") if profile else None
                if wants_specs and profile:
                    cores = profile.get("cpu_cores")
                    threads = profile.get("cpu_threads")
                    mhz = profile.get("cpu_max_mhz")
                    maker = profile.get("cpu_manufacturer")
                    bits = []
                    if maker:
                        bits.append(maker)
                    if cores:
                        bits.append(f"{cores} cores")
                    if threads:
                        bits.append(f"{threads} threads")
                    if mhz:
                        bits.append(f"{mhz} MHz max")
                    detail = f" ({', '.join(bits)})" if bits else ""
                    response_text = f"Your CPU is a {cpu_name}{detail}." if cpu_name else "Hardware information unavailable."
                    coordinator._safe_speak(response_text, interaction_id=coordinator.interaction_id)
                    mark_output()
                    coordinator._last_utterance_time = time.time()
                    coordinator.current_probe.mark("llm_end")
                    coordinator.current_probe.mark("tts_start")
                    coordinator.current_probe.mark("tts_end")
                    coordinator.current_probe.log_summary()
                    coordinator.latency_stats.add_probe(coordinator.current_probe)
                    finalize_watchdog()
                    return True
                response_text = (
                    f"Your CPU is a {cpu_name}."
                    if cpu_name
                    else "Hardware information unavailable."
                )
            elif subintent == "gpu":
                if gpus:
                    if wants_specs:
                        gpu_bits = []
                        for gpu in gpus:
                            name = gpu.get("name")
                            vram = gpu.get("vram_mb")
                            dv = gpu.get("driver_version")
                            detail = []
                            if vram:
                                detail.append(f"{vram}MB VRAM")
                            if dv:
                                detail.append(f"driver {dv}")
                            gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                        response_text = "Your GPU(s): " + "; ".join(gpu_bits) + "."
                        coordinator._safe_speak(response_text, interaction_id=coordinator.interaction_id)
                        mark_output()
                        coordinator._last_utterance_time = time.time()
                        coordinator.current_probe.mark("llm_end")
                        coordinator.current_probe.mark("tts_start")
                        coordinator.current_probe.mark("tts_end")
                        coordinator.current_probe.log_summary()
                        coordinator.latency_stats.add_probe(coordinator.current_probe)
                        finalize_watchdog()
                        return True
                    response_text = f"Your GPU is {gpus[0].get('name')}."
                else:
                    response_text = "No GPU detected."
            elif subintent == "os":
                os_name = profile.get("os") if profile else None
                response_text = (
                    f"You are running {os_name}."
                    if os_name
                    else "Hardware information unavailable."
                )
            elif subintent == "motherboard":
                board = profile.get("motherboard") if profile else None
                if wants_specs and profile:
                    bios = profile.get("bios_version")
                    sys_maker = profile.get("system_manufacturer")
                    sys_model = profile.get("system_model")
                    parts = []
                    if sys_maker or sys_model:
                        parts.append(" ".join(p for p in [sys_maker, sys_model] if p))
                    if bios:
                        parts.append(f"BIOS {bios}")
                    extra = f" ({', '.join(parts)})" if parts else ""
                    response_text = f"Your motherboard is {board}{extra}." if board else "Hardware information unavailable."
                    coordinator._safe_speak(response_text, interaction_id=coordinator.interaction_id)
                    mark_output()
                    coordinator._last_utterance_time = time.time()
                    coordinator.current_probe.mark("llm_end")
                    coordinator.current_probe.mark("tts_start")
                    coordinator.current_probe.mark("tts_end")
                    coordinator.current_probe.log_summary()
                    coordinator.latency_stats.add_probe(coordinator.current_probe)
                    finalize_watchdog()
                    return True
                response_text = (
                    f"Your motherboard is {board}."
                    if board
                    else "Hardware information unavailable."
                )
            else:
                cpu_name = profile.get("cpu") if profile else None
                ram_gb = profile.get("ram_gb") if profile else None
                gpu_name = gpus[0].get("name") if gpus else None
                if not cpu_name or ram_gb is None:
                    response_text = "Hardware information unavailable."
                else:
                    response_text = (
                        f"Your CPU is a {cpu_name}. "
                        f"You have {ram_gb} gigabytes of memory."
                    )
                    if gpu_name:
                        response_text += f" Your GPU is {gpu_name}."
                    if wants_specs and profile:
                        drives = profile.get("storage_drives") or []
                        if drives:
                            drive_bits = []
                            for d in drives:
                                name = d.get("model") or "Drive"
                                size = d.get("size_gb")
                                iface = d.get("interface")
                                detail = []
                                if size:
                                    detail.append(f"{size}GB")
                                if iface:
                                    detail.append(iface)
                                drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                            response_text += " Storage: " + "; ".join(drive_bits) + "."
        elif subintent == "temperature":
            temps = get_temperature_health()
            if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                response_text = "Temperature sensors are not available on this system."
            else:
                response_text = coordinator._format_temperature_response(temps)
        else:
            health = get_system_health()
            coordinator.logger.info(
                "[SYSTEM] cpu=%s ram=%s disk=%s",
                health.get("cpu_percent"),
                health.get("ram_percent"),
                health.get("disk_percent"),
            )
            response_text = coordinator._format_system_health(health)
        try:
            coordinator._safe_speak(response_text, interaction_id=coordinator.interaction_id)
            mark_output()
        except Exception:
            pass
        coordinator._last_utterance_time = time.time()
        coordinator.current_probe.mark("llm_end")
        coordinator.current_probe.mark("tts_start")
        coordinator.current_probe.mark("tts_end")
        coordinator.current_probe.log_summary()
        coordinator.latency_stats.add_probe(coordinator.current_probe)
        finalize_watchdog()
        return True

    return False
