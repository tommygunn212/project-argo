[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LiveKitExe = Join-Path $Root "livekit-server\livekit-server.exe"
$AgentFile = Join-Path $Root "livekit_realtime_agent.py"

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.Equals($LiveKitExe, [System.StringComparison]::OrdinalIgnoreCase)) -or
    ($_.CommandLine -and $_.CommandLine.Contains($AgentFile))
}

if (-not $targets) {
    Write-Host "No ARGO realtime voice processes were running."
    return
}

foreach ($proc in $targets) {
    Write-Host "Stopping PID $($proc.ProcessId): $($proc.Name)"
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    }
    catch {
        Write-Host "PID $($proc.ProcessId) was already stopped."
    }
}

Write-Host "ARGO realtime voice stopped."
