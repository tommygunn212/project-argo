"""Pure text formatting shared by the classic pipeline and coordinator."""

from __future__ import annotations


def format_system_health(health: dict) -> str:
    return (
        f"CPU at {health.get('cpu_percent')} percent. "
        f"Memory at {health.get('ram_percent')} percent. "
        f"Disk {health.get('disk_percent')} percent full."
    )


def format_system_memory_info(total_gb: float, used_pct: float, temps: dict) -> str:
    text = (
        f"Your system has {total_gb} gigabytes of memory installed. "
        f"Currently using about {used_pct} percent."
    )
    if temps.get("cpu") is not None:
        text += f" CPU temperature is {temps['cpu']} degrees."
    if temps.get("gpu") is not None:
        text += f" GPU temperature is {temps['gpu']} degrees."
    return text


def format_temperature_response(temps: dict) -> str:
    parts = []
    if temps.get("cpu") is not None:
        parts.append(f"CPU temperature is {temps['cpu']} degrees.")
    if temps.get("gpu") is not None:
        parts.append(f"GPU temperature is {temps['gpu']} degrees.")
    if not parts:
        return "Temperature sensors are not available on this system."
    return " ".join(parts) + " Normal."


def format_size_gb(gb: float) -> str:
    try:
        if gb >= 1024:
            return f"{round(gb / 1024, 2)} terabytes"
        gigs = int(gb)
        megs = int(round((gb - gigs) * 1024))
        if gigs > 0 and megs > 0:
            return f"{gigs} gigs {megs} megs"
        if gigs > 0:
            return f"{gigs} gigs"
        return f"{megs} megs"
    except Exception:
        return f"{gb} gigs"


def format_system_full_report(report: dict) -> str:
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
        suffix = f", with VRAM at {gpu_mem} percent" if gpu_mem is not None else ""
        parts.append(f"GPU usage is {gpu_pct} percent{suffix}.")

    temp_bits = []
    if health.get("cpu_temp") is not None:
        temp_bits.append(f"CPU {health['cpu_temp']}°C")
    if health.get("gpu_temp") is not None:
        temp_bits.append(f"GPU {health['gpu_temp']}°C")
    if temp_bits:
        parts.append("Temperatures: " + ", ".join(temp_bits) + ".")
    if uptime_seconds:
        parts.append(f"Uptime is {round(uptime_seconds / 3600, 1)} hours.")

    if disks:
        disk_bits = []
        for label, info in sorted(disks.items()):
            disk_bits.append(
                f"{label.replace(':', '')} drive is {info['percent']} percent full, "
                f"with {format_size_gb(info['free_gb'])} free out of {format_size_gb(info['total_gb'])}."
            )
        parts.append("Drives: " + " ".join(disk_bits))

    if network:
        net_bits = []
        for nic in network:
            segment = nic.get("name") or "Network"
            if nic.get("ip"):
                segment += f" {nic['ip']}"
            if nic.get("speed_mbps"):
                segment += f" {nic['speed_mbps']}Mbps"
            net_bits.append(segment)
        parts.append("Network: " + ", ".join(net_bits) + ".")

    if battery and battery.get("percent") is not None:
        status = "plugged in" if battery.get("plugged") else "on battery"
        parts.append(f"Battery is {battery['percent']} percent, {status}.")
    if fans:
        fan_bits = [f"{fan['label']} {fan['rpm']}RPM" for fan in fans if fan.get("rpm") is not None]
        if fan_bits:
            parts.append("Fans: " + ", ".join(fan_bits) + ".")
    return "System status. " + " ".join(parts) if parts else "Hardware information unavailable."


def format_ports_summary(ports: dict | None) -> str:
    if not ports:
        return "Ports information unavailable."
    bits = []
    for key, label, fallback in (
        ("serial", "Serial ports", "Unknown"),
        ("parallel", "Parallel ports", "Unknown"),
        ("usb_controllers", "USB controllers", "USB controller"),
    ):
        entries = ports.get(key) or []
        if entries:
            names = ", ".join(item.get("name") or item.get("device_id") or fallback for item in entries)
            bits.append(f"{label}: {names}.")
    return " ".join(bits).strip() or "Ports information unavailable."


def format_irq_summary(irqs: list | None, limit: int = 25) -> str:
    if not irqs:
        return "IRQ information unavailable."
    lines = []
    for irq in irqs[:limit]:
        name = irq.get("name") or irq.get("description") or "IRQ"
        prefix = f"IRQ {irq['irq']}" if irq.get("irq") is not None else "IRQ"
        lines.append(f"{prefix}: {name}")
    remaining = len(irqs) - len(lines)
    if remaining > 0:
        lines.append(f"({remaining} more)")
    return "; ".join(lines).strip() or "IRQ information unavailable."
