from core import system_response_formatter as formatter


def test_basic_health_and_temperature_responses_are_deterministic():
    health = {"cpu_percent": 10, "ram_percent": 20, "disk_percent": 30}

    assert formatter.format_system_health(health) == (
        "CPU at 10 percent. Memory at 20 percent. Disk 30 percent full."
    )
    assert formatter.format_temperature_response({}) == (
        "Temperature sensors are not available on this system."
    )
    assert formatter.format_temperature_response({"cpu": 42, "gpu": 51}) == (
        "CPU temperature is 42 degrees. GPU temperature is 51 degrees. Normal."
    )


def test_full_report_formats_all_supported_sections():
    report = {
        "health": {
            "cpu_percent": 10,
            "ram_percent": 20,
            "disk_percent": 30,
            "gpu_percent": 40,
            "gpu_mem_percent": 50,
            "cpu_temp": 42,
            "gpu_temp": 51,
        },
        "uptime_seconds": 7200,
        "disks": {"C:": {"percent": 30, "free_gb": 1.5, "total_gb": 2048}},
        "network": [{"name": "Ethernet", "ip": "192.0.2.1", "speed_mbps": 1000}],
        "battery": {"percent": 90, "plugged": True},
        "fans": [{"label": "CPU", "rpm": 1200}],
    }

    result = formatter.format_system_full_report(report)

    assert "CPU is 10 percent" in result
    assert "GPU usage is 40 percent, with VRAM at 50 percent" in result
    assert "C drive is 30 percent full, with 1 gigs 512 megs free out of 2.0 terabytes" in result
    assert "Ethernet 192.0.2.1 1000Mbps" in result
    assert "Battery is 90 percent, plugged in" in result
    assert "Fans: CPU 1200RPM" in result


def test_ports_irqs_and_empty_reports_have_explicit_fallbacks():
    assert formatter.format_system_full_report({}) == "Hardware information unavailable."
    assert formatter.format_ports_summary(None) == "Ports information unavailable."
    assert formatter.format_irq_summary(None) == "IRQ information unavailable."
    assert formatter.format_irq_summary([{"irq": 7, "name": "Timer"}], limit=1) == "IRQ 7: Timer"
