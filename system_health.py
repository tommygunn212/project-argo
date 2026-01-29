import os
import platform
import psutil


def get_memory_info():
    mem = psutil.virtual_memory()
    total_gb = round(mem.total / (1024**3), 1)
    used_pct = mem.percent
    return total_gb, used_pct


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


def get_temperature_health():
    temps = get_temperatures() or {}
    if temps is None:
        return {"error": "TEMPERATURE_UNAVAILABLE"}
    return temps


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
