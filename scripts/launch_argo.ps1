# One-click ARGO: (re)start the whole stack safely, then open the dashboard.
# This is what the "ARGO" taskbar button runs. Safe to click while ARGO is
# already running: start_argo_stack.ps1 drains the old worker first.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Host.UI.RawUI.WindowTitle = 'ARGO - starting'
Write-Host 'Starting ARGO - this can take up to a minute.' -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\start_argo_stack.ps1')
$code = $LASTEXITCODE
if ($code -and $code -ne 0) {
    Write-Host ''
    Write-Host "ARGO did not start cleanly (exit $code). Read the lines above." -ForegroundColor Yellow
    Read-Host 'Press Enter to close'
    exit $code
}
Start-Process 'http://localhost:8000/v2'
Write-Host 'ARGO is up - dashboard opened. This window closes in 5 seconds.' -ForegroundColor Green
Start-Sleep -Seconds 5
