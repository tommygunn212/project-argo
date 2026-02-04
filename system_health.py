# ============================================================================
# 1) IMPORTS
# ============================================================================
import os
import platform
import psutil
import time


# ============================================================================
# 1B) HARDWARE IDENTIFICATION
# ============================================================================
def get_hardware_info():
    """Get hardware identification: CPU model, GPU name, RAM size, OS."""
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu_name": platform.processor() or "Unknown CPU",
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "gpu_name": None,
    }
    
    # Try to get better CPU name on Windows
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            info["cpu_name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            winreg.CloseKey(key)
        except Exception:
            pass
    
    # Try to get GPU name via NVML
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info["gpu_name"] = pynvml.nvmlDeviceGetName(handle)
        if isinstance(info["gpu_name"], bytes):
            info["gpu_name"] = info["gpu_name"].decode("utf-8")
        pynvml.nvmlShutdown()
    except Exception:
        pass
    
    return info


# ============================================================================
# 2) MEMORY SNAPSHOT
# ============================================================================
def get_memory_info():
    mem = psutil.virtual_memory()
    total_gb = round(mem.total / (1024**3), 1)
    used_pct = mem.percent
    return total_gb, used_pct


# ============================================================================
# 3) TEMPERATURE SENSORS
# ============================================================================
def get_temperatures():
    temps = {}
    try:
        sensor_map = psutil.sensors_temperatures(fahrenheit=False)
        for _, entries in sensor_map.items():
            for entry in entries:
                if entry.current is None:
                    continue
                if "cpu" not in temps:
                    temps["cpu"] = round(entry.current, 1)
                    break
            if "cpu" in temps:
                break
    except Exception:
        pass

    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temps["gpu"] = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
        pynvml.nvmlShutdown()
    except Exception:
        pass

    return temps or None


# ============================================================================
# 4) TEMPERATURE HEALTH WRAPPER
# ============================================================================
def get_temperature_health():
    temps = get_temperatures() or {}
    if temps is None:
        return {"error": "TEMPERATURE_UNAVAILABLE"}
    return temps


# ============================================================================
# 5) SYSTEM HEALTH SNAPSHOT
# ============================================================================
def get_system_health():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    temps = get_temperatures() or {}

    health = {
        "cpu_percent": cpu,
        "ram_percent": mem.percent,
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "platform": platform.system(),
        "cpu_temp": temps.get("cpu"),
        "gpu_temp": temps.get("gpu"),
    }

    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        health["gpu_percent"] = util.gpu
        health["gpu_mem_percent"] = round((mem_info.used / mem_info.total) * 100, 1)
        pynvml.nvmlShutdown()
    except Exception:
        pass

    return health


# ============================================================================
# 5B) UPTIME / NETWORK / BATTERY / FANS
# ============================================================================
def get_uptime_seconds() -> float:
    try:
        return max(0.0, time.time() - psutil.boot_time())
    except Exception:
        return 0.0


def get_network_info():
    info = []
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for name, st in stats.items():
            if not st.isup:
                continue
            ipv4 = None
            for addr in addrs.get(name, []):
                if getattr(addr, "family", None) == getattr(psutil, "AF_LINK", None):
                    continue
                if str(addr.family).endswith("AF_INET"):
                    ipv4 = addr.address
                    break
            info.append({
                "name": name,
                "speed_mbps": st.speed,
                "ip": ipv4,
            })
    except Exception:
        pass
    return info


def get_battery_info():
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return None
        return {
            "percent": batt.percent,
            "plugged": batt.power_plugged,
        }
    except Exception:
        return None


def get_fan_info():
    try:
        fans = psutil.sensors_fans()
        if not fans:
            return None
        out = []
        for group, entries in fans.items():
            for entry in entries:
                if entry.current is None:
                    continue
                out.append({
                    "label": entry.label or group,
                    "rpm": entry.current,
                })
        return out or None
    except Exception:
        return None


def get_system_full_report():
    """Aggregate full system snapshot for deterministic reporting."""
    return {
        "health": get_system_health(),
        "disks": get_disk_info(),
        "uptime_seconds": get_uptime_seconds(),
        "network": get_network_info(),
        "battery": get_battery_info(),
        "fans": get_fan_info(),
    }


# ============================================================================
# 6) DISK INVENTORY (PER-MOUNT)
# ============================================================================
def get_disk_info():
    disks = {}
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception:
        partitions = []

    for part in partitions:
        mount = part.mountpoint
        try:
            usage = psutil.disk_usage(mount)
        except Exception:
            continue

        if os.name == "nt":
            if len(mount) >= 2 and mount[1] == ":":
                label = mount[:2].upper()
            else:
                label = mount
        else:
            label = mount

        disks[label] = {
            "percent": round(usage.percent, 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "total_gb": round(usage.total / (1024**3), 1),
        }

    return disks
