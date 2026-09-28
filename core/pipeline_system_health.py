"""System-health response routing for the classic pipeline."""

from __future__ import annotations

import re
from typing import Any, Protocol

from core.intent_parser import IntentType
from system_health import (
    get_disk_info,
    get_system_full_report,
    get_system_health,
    get_temperature_health,
)
from system_profile import get_gpu_profile, get_system_profile


class SystemHealthPipeline(Protocol):
    """Minimal pipeline surface required by system-health routing."""

    logger: Any

    def _evaluate_gates(self, *args: Any) -> tuple[bool, str]: ...

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool: ...

    def _format_system_full_report(self, report: Any) -> str: ...

    def _format_subsystem_summary(self) -> str: ...

    def _format_gate_summary(self, *args: Any) -> str: ...

    def _format_governance_summary(self) -> str: ...

    def _format_ports_summary(self, ports: Any) -> str: ...

    def _format_irq_summary(self, irqs: Any) -> str: ...

    def _format_temperature_response(self, temperatures: Any) -> str: ...

    def _format_system_health(self, health: Any) -> str: ...


def respond_with_system_health(
    pipeline: SystemHealthPipeline,
    user_text,
    intent,
    interaction_id,
    replay_mode,
    overrides,
) -> bool:
    """Answer system-health questions without invoking the LLM."""

    is_system_status = bool(intent and intent.intent_type == IntentType.SYSTEM_STATUS)

    def _finish(message: str) -> bool:
        return pipeline._deliver_canonical_response(
            message,
            interaction_id,
            replay_mode,
            overrides,
            enforce_confidence=not is_system_status,
            force_tts=is_system_status,
            suppress_barge_in_seconds=1.5 if is_system_status else None,
        )

    if not is_system_status:
        allowed, reason = pipeline._evaluate_gates("system_health", "system_health", interaction_id)
        if not allowed:
            return _finish(f"System health access blocked by policy ({reason}).")

    subintent = getattr(intent, "subintent", None) if intent else None
    if intent and intent.intent_type == IntentType.SYSTEM_STATUS and not subintent:
        subintent = "full"
    raw_text_lower = (getattr(intent, "raw_text", None) or user_text or "").lower()

    if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
        disks = get_disk_info()
        if not disks:
            return _finish("Hardware information unavailable.")
        drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
        if not drive_match:
            drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
        if drive_match:
            letter = drive_match.group(1).upper()
            key = f"{letter}:"
            info = disks.get(key) or disks.get(letter)
            if info:
                return _finish(
                    f"{letter} drive is {info['percent']} percent full, with {info['free_gb']} gigabytes free."
                )
            return _finish("Hardware information unavailable.")
        if "fullest" in raw_text_lower or "most used" in raw_text_lower:
            disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
            return _finish(f"{disk} is the fullest drive at {info['percent']} percent used.")
        if "most free" in raw_text_lower or "most space" in raw_text_lower:
            disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
            return _finish(f"{disk} has the most free space at {info['free_gb']} gigabytes free.")
        total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
        return _finish(f"You have {total_free} gigabytes free across {len(disks)} drives.")

    if subintent == "full":
        report = get_system_full_report()
        message = pipeline._format_system_full_report(report)
        message = f"{message} {pipeline._format_subsystem_summary()} {pipeline._format_gate_summary('system_health', 'system_health')}"
        raw_text_lower = (getattr(intent, "raw_text", None) or user_text or "").lower()
        if any(term in raw_text_lower for term in {"law", "laws", "governance", "gate", "gates"}):
            message = f"{message} {pipeline._format_governance_summary()}"
        return _finish(message)

    if subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
        profile = get_system_profile()
        gpus = get_gpu_profile()
        wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
        wants_ports = "port" in raw_text_lower or "usb" in raw_text_lower
        wants_irqs = "irq" in raw_text_lower or "interrupt" in raw_text_lower
        wants_drives = "drive" in raw_text_lower or "disk" in raw_text_lower or "storage" in raw_text_lower
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
                if ram_gb is not None:
                    return _finish(f"Your system has {ram_gb} gigabytes of memory{extra_text}.")
                return _finish("Hardware information unavailable.")
            return _finish(
                f"Your system has {ram_gb} gigabytes of memory." if ram_gb is not None else "Hardware information unavailable."
            )
        if subintent == "cpu":
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
                if cpu_name:
                    return _finish(f"Your CPU is a {cpu_name}{detail}.")
                return _finish("Hardware information unavailable.")
            return _finish(
                f"Your CPU is a {cpu_name}." if cpu_name else "Hardware information unavailable."
            )
        if subintent == "gpu":
            if gpus:
                if wants_specs:
                    gpu_bits = []
                    for gpu in gpus:
                        name = gpu.get("name")
                        vram = gpu.get("vram_mb")
                        driver_version = gpu.get("driver_version")
                        detail = []
                        if vram:
                            detail.append(f"{vram}MB VRAM")
                        if driver_version:
                            detail.append(f"driver {driver_version}")
                        gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                    return _finish("Your GPU(s): " + "; ".join(gpu_bits) + ".")
                return _finish(f"Your GPU is {gpus[0].get('name')}.")
            return _finish("No GPU detected.")
        if subintent == "os":
            os_name = profile.get("os") if profile else None
            return _finish(f"You are running {os_name}." if os_name else "Hardware information unavailable.")
        if subintent == "motherboard":
            board = profile.get("motherboard") if profile else None
            if wants_specs and profile:
                bios = profile.get("bios_version")
                sys_maker = profile.get("system_manufacturer")
                sys_model = profile.get("system_model")
                parts = []
                if sys_maker or sys_model:
                    parts.append(" ".join(p for p in [sys_maker, sys_model] if p).strip())
                if bios:
                    parts.append(f"BIOS {bios}")
                extra = f" ({', '.join(parts)})" if parts else ""
                if board:
                    return _finish(f"Your motherboard is {board}{extra}.")
                return _finish("Hardware information unavailable.")
            return _finish(f"Your motherboard is {board}." if board else "Hardware information unavailable.")
        cpu_name = profile.get("cpu") if profile else None
        ram_gb = profile.get("ram_gb") if profile else None
        if not cpu_name or ram_gb is None:
            return _finish("Hardware information unavailable.")
        response = f"Your CPU is a {cpu_name}. You have {ram_gb} gigabytes of memory."
        if gpus:
            response += f" Your GPU is {gpus[0].get('name')}."
        if (wants_specs or wants_drives) and profile:
            drives = profile.get("storage_drives") or []
            if drives:
                drive_bits = []
                for drive in drives:
                    name = drive.get("model") or "Drive"
                    size = drive.get("size_gb")
                    iface = drive.get("interface")
                    detail = []
                    if size:
                        detail.append(f"{size}GB")
                    if iface:
                        detail.append(iface)
                    drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                response += " Storage: " + "; ".join(drive_bits) + "."
        if wants_ports:
            response += " " + pipeline._format_ports_summary(profile.get("ports") if profile else None)
        if wants_irqs:
            response += " " + pipeline._format_irq_summary(profile.get("irqs") if profile else None)
        return _finish(response)

    if subintent == "temperature":
        temps = get_temperature_health()
        if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
            return _finish("Temperature sensors are not available on this system.")
        return _finish(pipeline._format_temperature_response(temps))

    health = get_system_health()
    pipeline.logger.info(
        "[SYSTEM] cpu=%s ram=%s disk=%s",
        health.get("cpu_percent"),
        health.get("ram_percent"),
        health.get("disk_percent"),
    )
    return _finish(pipeline._format_system_health(health))

