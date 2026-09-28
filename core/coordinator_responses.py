"""Deterministic response formatting for :class:`core.coordinator.Coordinator`."""

from __future__ import annotations

import re
from typing import Optional

from core import system_response_formatter as system_format


class CoordinatorResponseMixin:
    def _build_count_response(self, text: str) -> str:
        target = self._parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def _parse_count_target(self, text: str) -> int:
        if not text:
            return 5
        match = re.search(r"\b(\d+)\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 5
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        for word, value in words.items():
            if re.search(rf"\b{word}\b", text, flags=re.IGNORECASE):
                return value
        return 5

    def _format_system_health(self, health: dict) -> str:
        return system_format.format_system_health(health)

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        return system_format.format_system_memory_info(total_gb, used_pct, temps)

    def _format_temperature_response(self, temps: dict) -> str:
        return system_format.format_temperature_response(temps)

    def _format_system_full_report(self, report: dict) -> str:
        health = report.get("health", {}) or {}
        disks = report.get("disks", {}) or {}
        uptime_seconds = report.get("uptime_seconds", 0) or 0
        network = report.get("network", []) or []
        battery = report.get("battery")
        fans = report.get("fans")

        parts = []
        cpu_pct = health.get("cpu_percent")
        ram_pct = health.get("ram_percent")
        disk_pct = health.get("disk_percent")
        gpu_pct = health.get("gpu_percent")
        gpu_mem = health.get("gpu_mem_percent")
        if cpu_pct is not None and ram_pct is not None and disk_pct is not None:
            parts.append(f"CPU is {cpu_pct} percent. Memory is {ram_pct} percent. Disk usage is {disk_pct} percent.")
        if gpu_pct is not None:
            if gpu_mem is not None:
                parts.append(f"GPU usage is {gpu_pct} percent, with VRAM at {gpu_mem} percent.")
            else:
                parts.append(f"GPU usage is {gpu_pct} percent.")

        cpu_temp = health.get("cpu_temp")
        gpu_temp = health.get("gpu_temp")
        if cpu_temp is not None or gpu_temp is not None:
            temp_bits = []
            if cpu_temp is not None:
                temp_bits.append(f"CPU {cpu_temp}°C")
            if gpu_temp is not None:
                temp_bits.append(f"GPU {gpu_temp}°C")
            parts.append("Temperatures: " + ", ".join(temp_bits) + ".")

        if uptime_seconds:
            hours = round(uptime_seconds / 3600, 1)
            parts.append(f"Uptime is {hours} hours.")

        if disks:
            disk_bits = []
            for label, info in sorted(disks.items()):
                drive_label = label.replace(":", "")
                free_text = self._format_size_gb(info["free_gb"])
                total_text = self._format_size_gb(info["total_gb"])
                disk_bits.append(
                    f"{drive_label} drive is {info['percent']} percent full, with {free_text} free out of {total_text}."
                )
            parts.append("Drives: " + " ".join(disk_bits))

        if network:
            net_bits = []
            for nic in network:
                label = nic.get("name")
                ip = nic.get("ip")
                speed = nic.get("speed_mbps")
                seg = label or "Network"
                if ip:
                    seg += f" {ip}"
                if speed:
                    seg += f" {speed}Mbps"
                net_bits.append(seg)
            parts.append("Network: " + ", ".join(net_bits) + ".")

        if battery:
            pct = battery.get("percent")
            plugged = battery.get("plugged")
            if pct is not None:
                status = "plugged in" if plugged else "on battery"
                parts.append(f"Battery is {pct} percent, {status}.")

        if fans:
            fan_bits = [f"{f['label']} {f['rpm']}RPM" for f in fans if f.get("rpm") is not None]
            if fan_bits:
                parts.append("Fans: " + ", ".join(fan_bits) + ".")

        if not parts:
            return "Hardware information unavailable."

        return "System status. " + " ".join(parts)

    def _format_size_gb(self, gb: float) -> str:
        try:
            if gb >= 1024:
                tb = round(gb / 1024, 2)
                return f"{tb} terabytes"
            gigs = int(gb)
            megs = int(round((gb - gigs) * 1024))
            if gigs > 0 and megs > 0:
                return f"{gigs} gigs {megs} megs"
            if gigs > 0:
                return f"{gigs} gigs"
            return f"{megs} megs"
        except Exception:
            return f"{gb} gigs"

    def _safe_speak(self, text: str, interaction_id: Optional[str] = None) -> None:
        if not text or not text.strip():
            return
        if not self.runtime_overrides.get("tts_enabled", True):
            return
        current_interaction_id = interaction_id or self.interaction_id
        if self._response_interaction_id != current_interaction_id:
            self._response_interaction_id = current_interaction_id
            self._response_committed = False
        if self._response_committed:
            self.logger.warning(
                "[Response] Duplicate response suppressed (interaction_id=%s)",
                current_interaction_id,
            )
            return
        self.logger.info(f"Argo: {text}")
        self._response_committed = True
        try:
            self.acquire_audio("TTS")
        except Exception as e:
            self.logger.warning(f"[TTS] Audio ownership denied: {e}")
            return
        try:
            self.sink.speak(text, interaction_id=interaction_id or self.interaction_id)
        finally:
            self.release_audio("TTS")
