# Start ARGO: livekit-server (if needed) + backend + realtime worker, from the venv.
#
#   .\scripts\start_argo_stack.ps1                 report-only: refuses if orphans are suspected
#   .\scripts\start_argo_stack.ps1 -CleanOrphans   also stops CONFIRMED ARGO executor orphans
#
# Nothing is ever stopped without -CleanOrphans, and even then only processes
# that core.runtime_guard can tie to I:\argo by ARGO-specific evidence (working
# directory is I:\argo, plus ARGO's venv mapped in memory or ARGO in argv).
# A parentless python talking to LiveKit that is NOT ARGO's is reported and
# left alone - it is somebody else's process.
#
# Why any of this exists: force-stopping a worker orphans its executor child,
# which keeps its LiveKit registration and keeps being handed jobs it cannot
# run. Eight of those made ARGO answer 2 dispatches in 10. The fix is to drain
# (the worker shuts itself down through the framework and deregisters), so a
# drain request is the only way this script asks a worker to stop.

param([switch]$CleanOrphans)

$ErrorActionPreference = "Stop"
$Root  = "I:\argo"
$Py    = Join-Path $Root ".venv\Scripts\python.exe"
$Logs  = Join-Path $Root "runtime\logs"
$Locks = Join-Path $Root "runtime\locks"
$Drain = Join-Path $Locks "realtime-worker.drain"
New-Item -ItemType Directory -Force -Path $Logs, $Locks | Out-Null

function Get-LiveKitPort {
    try { $cfg = Get-Content (Join-Path $Root "config.json") -Raw | ConvertFrom-Json
          $u = [uri]$cfg.livekit.url; if ($u.Port -gt 0) { return $u.Port } } catch {}
    return 7880
}
$Port = Get-LiveKitPort

# ---- 1. ask the current worker to drain --------------------------------------
$lockFile = Join-Path $Locks "realtime-worker.lock"
if (Test-Path $lockFile) {
    try { $held = Get-Content $lockFile -Raw | ConvertFrom-Json } catch { $held = $null }
    if ($held -and (Get-Process -Id $held.pid -ErrorAction SilentlyContinue)) {
        Write-Host "Asking worker pid $($held.pid) to drain..."
        Set-Content -Path $Drain -Value "drain"
        $deadline = (Get-Date).AddSeconds(45)
        while ((Get-Date) -lt $deadline -and (Get-Process -Id $held.pid -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 400 }
        if (Get-Process -Id $held.pid -ErrorAction SilentlyContinue) {
            Remove-Item $Drain -ErrorAction SilentlyContinue
            Write-Host "  pid $($held.pid) did not exit on a drain request (started $($held.started_human))." -ForegroundColor Yellow
            Write-Host "  Not stopping it. Close it yourself (or Ctrl+C in its window) and re-run." -ForegroundColor Yellow
            exit 2
        }
        Write-Host "  drained cleanly."
    }
}
Remove-Item $Drain, $lockFile -ErrorAction SilentlyContinue

# The backend holds no LiveKit registration; a plain stop leaves nothing behind.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*$Root\main.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $Locks "main.lock") -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# ---- 2. orphans: report by default, clean only on request ---------------------
if ($CleanOrphans) {
    Write-Host "Orphan cleanup requested (-CleanOrphans). Only confirmed ARGO executors will be stopped:"
    & $Py -m core.runtime_guard --clean
    Start-Sleep -Seconds 2
}
Write-Host "Orphan check (read-only):"
& $Py -m core.runtime_guard --report
if ($LASTEXITCODE -eq 2) {
    Write-Host ""
    Write-Host "Refusing to start a worker next to suspected orphans: it would join a job lottery." -ForegroundColor Yellow
    Write-Host "  Re-run with -CleanOrphans to stop the ones confirmed as ARGO's." -ForegroundColor Yellow
    Write-Host "  Anything reported as 'NOT confirmed as ARGO' is not this script's to stop." -ForegroundColor Yellow
    exit 2
}

# ---- 3. livekit-server ------------------------------------------------------------
if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "Starting livekit-server..."
    Start-Process -FilePath (Join-Path $Root "livekit-server\livekit-server.exe") `
        -ArgumentList '--config', (Join-Path $Root "livekit-server\livekit.yaml") `
        -WorkingDirectory (Join-Path $Root "livekit-server") -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Logs "livekit-server.log") `
        -RedirectStandardError  (Join-Path $Logs "livekit-server.err.log")
    Start-Sleep -Seconds 6
}

# ---- 4. backend + worker ------------------------------------------------------------
# Keep the previous worker's last words. The restart used to overwrite
# worker.out.log, which is exactly where "did it drain, and how" was recorded.
foreach ($name in 'worker', 'main') {
    $cur = Join-Path $Logs "$name.out.log"; $err = Join-Path $Logs "$name.err.log"
    if (Test-Path $cur) { Move-Item $cur (Join-Path $Logs "$name.prev.out.log") -Force }
    if (Test-Path $err) { Move-Item $err (Join-Path $Logs "$name.prev.err.log") -Force }
}

Write-Host "Starting backend..."
Start-Process -FilePath $Py -ArgumentList '-u', (Join-Path $Root 'main.py') `
    -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'main.out.log') `
    -RedirectStandardError  (Join-Path $Logs 'main.err.log')
Start-Sleep -Seconds 8

Write-Host "Starting realtime worker..."
Start-Process -FilePath $Py -ArgumentList '-u', (Join-Path $Root 'livekit_realtime_agent.py'), 'start' `
    -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'worker.out.log') `
    -RedirectStandardError  (Join-Path $Logs 'worker.err.log')
Start-Sleep -Seconds 12

# ---- 5. prove it -----------------------------------------------------------------------
Write-Host ""
foreach ($p in $Port, 8000, 8001) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    Write-Host ("  {0,-5} {1}" -f $p, $(if ($c) { "PID $($c.OwningProcess)" } else { "NOT LISTENING" }))
}
$held = Get-ChildItem $Locks -Filter *.lock -ErrorAction SilentlyContinue | ForEach-Object { $_.BaseName }
Write-Host "  locks: $($held -join ', ')"
Write-Host ""
Write-Host "Dispatch check (a placeholder alone does not count):"
& $Py (Join-Path $Root "tools\dispatch_probe.py") 2>&1 | Select-String -Pattern "PASS|FAIL" | ForEach-Object { Write-Host "  $_" }
