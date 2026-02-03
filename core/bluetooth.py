"""
Bluetooth status and control (Windows).
Deterministic, no LLM fallback.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any


AUDIO_DEVICE_HINTS = {
    "headset",
    "headphones",
    "earbuds",
    "speaker",
    "airpods",
}


def _run_powershell(script: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _parse_json(output: str) -> dict[str, Any] | None:
    try:
        return json.loads(output) if output else None
    except Exception:
        return None


def get_bluetooth_status() -> dict[str, Any]:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$devices = Get-PnpDevice -Class Bluetooth | Where-Object { $_.FriendlyName }
$adapters = $devices | Where-Object { $_.FriendlyName -match 'Bluetooth' -and $_.Class -eq 'Bluetooth' }
$adapterPresent = $false
$adapterEnabled = $false
if ($adapters) {
  $adapterPresent = $true
  $adapterEnabled = ($adapters | Where-Object { $_.Status -eq 'OK' } | Select-Object -First 1) -ne $null
}
$deviceObjs = @()
foreach ($d in $devices) {
  $connected = $false
  try {
    $prop = Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_Connected'
    if ($prop -and $prop.Data -eq $true) { $connected = $true }
  } catch {}
  $deviceObjs += [pscustomobject]@{
    name = $d.FriendlyName
    instance_id = $d.InstanceId
    status = $d.Status
    connected = $connected
  }
}
$paired = $deviceObjs | Select-Object -ExpandProperty name | Sort-Object -Unique
$connectedNames = $deviceObjs | Where-Object { $_.connected } | Select-Object -ExpandProperty name | Sort-Object -Unique
$result = [pscustomobject]@{
  adapter_present = $adapterPresent
  adapter_enabled = $adapterEnabled
  paired_devices = $paired
  connected_devices = $connectedNames
  devices = $deviceObjs
}
$result | ConvertTo-Json -Compress
"""
    code, out, _ = _run_powershell(script)
    data = _parse_json(out) if code == 0 else None
    if not data:
        return {
            "adapter_present": False,
            "adapter_enabled": False,
            "paired_devices": [],
            "connected_devices": [],
            "devices": [],
            "audio_device_active": False,
        }
    connected = data.get("connected_devices") or []
    audio_active = any(
        any(hint in name.lower() for hint in AUDIO_DEVICE_HINTS)
        for name in connected
        if isinstance(name, str)
    )
    data["audio_device_active"] = audio_active
    return data


def set_bluetooth_enabled(enabled: bool) -> tuple[bool, str]:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$adapters = Get-PnpDevice -Class Bluetooth | Where-Object { $_.FriendlyName -match 'Bluetooth' -and $_.Class -eq 'Bluetooth' }
if (-not $adapters) {
  [pscustomobject]@{ ok=$false; reason='adapter_not_found' } | ConvertTo-Json -Compress
  exit
}
foreach ($a in $adapters) {
  if (%s) { Enable-PnpDevice -InstanceId $a.InstanceId -Confirm:$false | Out-Null }
  else { Disable-PnpDevice -InstanceId $a.InstanceId -Confirm:$false | Out-Null }
}
[pscustomobject]@{ ok=$true } | ConvertTo-Json -Compress
""" % ("$true" if enabled else "$false")
    code, out, err = _run_powershell(script)
    data = _parse_json(out) if code == 0 else None
    if data and data.get("ok"):
        return True, "Bluetooth enabled." if enabled else "Bluetooth disabled."
    return False, "Bluetooth adapter not detected." if data and data.get("reason") == "adapter_not_found" else err or "Bluetooth control failed."


def _match_device(status: dict[str, Any], target: str) -> list[dict[str, Any]]:
    devices = status.get("devices") or []
    if not target:
        return []
    target_lower = target.lower()
    matches = []
    for dev in devices:
        name = dev.get("name") or ""
        if target_lower in name.lower():
            matches.append(dev)
    return matches


def connect_device(target: str) -> tuple[bool, str]:
    status = get_bluetooth_status()
    matches = _match_device(status, target)
    if not matches:
        return False, "No matching paired device found."
    if len(matches) > 1:
        names = ", ".join(sorted({m.get("name") for m in matches if m.get("name")}))
        return False, f"Multiple matches: {names}. Please specify the device name."
    instance_id = matches[0].get("instance_id")
    if not instance_id:
        return False, "Device instance not available."
    script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false | Out-Null
[pscustomobject]@{{ ok=$true }} | ConvertTo-Json -Compress
"""
    code, out, err = _run_powershell(script)
    data = _parse_json(out) if code == 0 else None
    if data and data.get("ok"):
        return True, f"Connected to {matches[0].get('name')}."
    return False, err or "Bluetooth connect failed."


def disconnect_device(target: str) -> tuple[bool, str]:
    status = get_bluetooth_status()
    matches = _match_device(status, target)
    if not matches:
        return False, "No matching paired device found."
    if len(matches) > 1:
        names = ", ".join(sorted({m.get("name") for m in matches if m.get("name")}))
        return False, f"Multiple matches: {names}. Please specify the device name."
    instance_id = matches[0].get("instance_id")
    if not instance_id:
        return False, "Device instance not available."
    script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
Disable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false | Out-Null
[pscustomobject]@{{ ok=$true }} | ConvertTo-Json -Compress
"""
    code, out, err = _run_powershell(script)
    data = _parse_json(out) if code == 0 else None
    if data and data.get("ok"):
        return True, f"Disconnected {matches[0].get('name')}."
    return False, err or "Bluetooth disconnect failed."


def pair_device(_: str | None = None) -> tuple[bool, str]:
    return False, "Pairing requires Windows Bluetooth settings."
