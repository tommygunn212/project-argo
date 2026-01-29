import platform
import psutil
import wmi

_SYSTEM_PROFILE = None
_GPU_PROFILE = None


def get_system_profile():
    global _SYSTEM_PROFILE
    if _SYSTEM_PROFILE is None:
        c = wmi.WMI()

        cpu = c.Win32_Processor()[0].Name
        ram_gb = round(psutil.virtual_memory().total / (1024**3))

        board = c.Win32_BaseBoard()[0]
        motherboard = f"{board.Manufacturer} {board.Product}"

        os_name = platform.system()
        os_version = platform.release()

        _SYSTEM_PROFILE = {
            "cpu": cpu,
            "ram_gb": ram_gb,
            "motherboard": motherboard,
            "os": f"{os_name} {os_version}",
        }
    return _SYSTEM_PROFILE


def get_gpu_profile():
    global _GPU_PROFILE
    if _GPU_PROFILE is None:
        gpus = []
        for gpu in wmi.WMI().Win32_VideoController():
            gpus.append({
                "name": gpu.Name,
                "vram_mb": gpu.AdapterRAM // (1024 * 1024),
            })
        _GPU_PROFILE = gpus
    return _GPU_PROFILE
