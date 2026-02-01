# ============================================================================
# 1) IMPORTS
# ============================================================================
import platform
import psutil
import wmi

# ============================================================================
# 2) CACHED PROFILES (LOAD ONCE)
# ============================================================================
_SYSTEM_PROFILE = None
_GPU_PROFILE = None
_PORTS_PROFILE = None
_IRQ_PROFILE = None


# ============================================================================
# 3) SYSTEM PROFILE (CPU/RAM/BOARD/OS)
# ============================================================================
def get_system_profile():
    global _SYSTEM_PROFILE, _PORTS_PROFILE, _IRQ_PROFILE
    if _SYSTEM_PROFILE is None:
        c = wmi.WMI()

        cpu = None
        cpu_cores = None
        cpu_threads = None
        cpu_max_mhz = None
        cpu_manufacturer = None
        try:
            cpu_obj = c.Win32_Processor()[0]
            cpu = cpu_obj.Name
            cpu_cores = getattr(cpu_obj, "NumberOfCores", None)
            cpu_threads = getattr(cpu_obj, "NumberOfLogicalProcessors", None)
            cpu_max_mhz = getattr(cpu_obj, "MaxClockSpeed", None)
            cpu_manufacturer = getattr(cpu_obj, "Manufacturer", None)
        except Exception:
            pass

        ram_gb = round(psutil.virtual_memory().total / (1024**3))
        memory_speed_mhz = None
        memory_modules = None
        try:
            mem_modules = c.Win32_PhysicalMemory()
            speeds = [m.Speed for m in mem_modules if getattr(m, "Speed", None)]
            if speeds:
                memory_speed_mhz = int(sum(speeds) / len(speeds))
            memory_modules = len(mem_modules) if mem_modules else None
        except Exception:
            pass

        motherboard = None
        board_maker = None
        board_product = None
        try:
            board = c.Win32_BaseBoard()[0]
            board_maker = getattr(board, "Manufacturer", None)
            board_product = getattr(board, "Product", None)
            if board_maker or board_product:
                motherboard = " ".join(p for p in [board_maker, board_product] if p)
        except Exception:
            pass

        bios_version = None
        try:
            bios = c.Win32_BIOS()[0]
            bios_version = getattr(bios, "SMBIOSBIOSVersion", None)
        except Exception:
            pass

        system_manufacturer = None
        system_model = None
        try:
            cs = c.Win32_ComputerSystem()[0]
            system_manufacturer = getattr(cs, "Manufacturer", None)
            system_model = getattr(cs, "Model", None)
        except Exception:
            pass

        storage_drives = []
        try:
            for drive in c.Win32_DiskDrive():
                size_gb = None
                try:
                    size_gb = round(int(drive.Size) / (1024**3), 1) if getattr(drive, "Size", None) else None
                except Exception:
                    size_gb = None
                storage_drives.append({
                    "model": getattr(drive, "Model", None),
                    "size_gb": size_gb,
                    "interface": getattr(drive, "InterfaceType", None),
                })
        except Exception:
            pass

        ports = None
        try:
            if _PORTS_PROFILE is None:
                serial_ports = []
                parallel_ports = []
                usb_controllers = []
                for port in c.Win32_SerialPort():
                    serial_ports.append({
                        "name": getattr(port, "Name", None),
                        "device_id": getattr(port, "DeviceID", None),
                        "description": getattr(port, "Description", None),
                    })
                for port in c.Win32_ParallelPort():
                    parallel_ports.append({
                        "name": getattr(port, "Name", None),
                        "device_id": getattr(port, "DeviceID", None),
                        "description": getattr(port, "Description", None),
                    })
                for controller in c.Win32_USBController():
                    usb_controllers.append({
                        "name": getattr(controller, "Name", None),
                        "device_id": getattr(controller, "DeviceID", None),
                        "manufacturer": getattr(controller, "Manufacturer", None),
                    })
                _PORTS_PROFILE = {
                    "serial": serial_ports,
                    "parallel": parallel_ports,
                    "usb_controllers": usb_controllers,
                }
            ports = _PORTS_PROFILE
        except Exception:
            ports = None

        irqs = None
        try:
            if _IRQ_PROFILE is None:
                irq_list = []
                for irq in c.Win32_IRQResource():
                    irq_list.append({
                        "irq": getattr(irq, "IRQNumber", None),
                        "name": getattr(irq, "Name", None),
                        "description": getattr(irq, "Description", None),
                    })
                _IRQ_PROFILE = irq_list
            irqs = _IRQ_PROFILE
        except Exception:
            irqs = None

        os_name = platform.system()
        os_version = platform.release()

        _SYSTEM_PROFILE = {
            "cpu": cpu,
            "cpu_manufacturer": cpu_manufacturer,
            "cpu_cores": cpu_cores,
            "cpu_threads": cpu_threads,
            "cpu_max_mhz": cpu_max_mhz,
            "ram_gb": ram_gb,
            "memory_speed_mhz": memory_speed_mhz,
            "memory_modules": memory_modules,
            "motherboard": motherboard,
            "motherboard_maker": board_maker,
            "motherboard_product": board_product,
            "bios_version": bios_version,
            "system_manufacturer": system_manufacturer,
            "system_model": system_model,
            "storage_drives": storage_drives,
            "ports": ports,
            "irqs": irqs,
            "os": f"{os_name} {os_version}",
        }
    return _SYSTEM_PROFILE


# ============================================================================
# 4) GPU PROFILE (NAME/VRAM)
# ============================================================================
def get_gpu_profile():
    global _GPU_PROFILE
    if _GPU_PROFILE is None:
        gpus = []
        for gpu in wmi.WMI().Win32_VideoController():
            vram_mb = None
            try:
                vram_mb = gpu.AdapterRAM // (1024 * 1024)
            except Exception:
                vram_mb = None
            gpus.append({
                "name": gpu.Name,
                "vram_mb": vram_mb,
                "driver_version": getattr(gpu, "DriverVersion", None),
            })
        _GPU_PROFILE = gpus
    return _GPU_PROFILE
