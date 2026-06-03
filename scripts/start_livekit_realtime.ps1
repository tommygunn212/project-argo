[CmdletBinding()]
param(
    [string]$LiveKitUrl = "ws://127.0.0.1:7880",
    [string]$ApiKey = "devkey",
    [string]$ApiSecret = "devsecretdevsecretdevsecretdevsecretdevsecret",
    [string]$Room = "argo-live",
    [string]$AgentIdentity = "argo-realtime"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LiveKitExe = Join-Path $Root "livekit-server\livekit-server.exe"
$LiveKitConfig = Join-Path $Root "livekit-server\livekit.yaml"
$AgentFile = Join-Path $Root "livekit_realtime_agent.py"
$RuntimeDir = Join-Path $Root "runtime\livekit"
$LogDir = Join-Path $RuntimeDir "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(350)) {
            $client.Close()
            return $false
        }
        $client.EndConnect($connect)
        $client.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Get-AgentProcess {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($AgentFile) }
}

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}
if (-not (Test-Path $LiveKitExe)) {
    throw "LiveKit server not found: $LiveKitExe"
}
if (-not (Test-Path $AgentFile)) {
    throw "Realtime agent not found: $AgentFile"
}

Import-DotEnv (Join-Path $Root ".env")

if (-not $env:OPENAI_API_KEY) {
    throw "OPENAI_API_KEY is required before starting ARGO realtime voice."
}

$env:LIVEKIT_URL = $LiveKitUrl
$env:LIVEKIT_API_KEY = $ApiKey
$env:LIVEKIT_API_SECRET = $ApiSecret

if (-not (Test-TcpPort -HostName "127.0.0.1" -Port 7880)) {
    $serverOut = Join-Path $LogDir "livekit-server.out.log"
    $serverErr = Join-Path $LogDir "livekit-server.err.log"
    Start-Process `
        -FilePath $LiveKitExe `
        -ArgumentList @("--config", $LiveKitConfig) `
        -WorkingDirectory (Split-Path $LiveKitExe -Parent) `
        -RedirectStandardOutput $serverOut `
        -RedirectStandardError $serverErr `
        -WindowStyle Hidden `
        -PassThru | Out-Null
    Start-Sleep -Milliseconds 900
}

$agent = Get-AgentProcess | Select-Object -First 1
if (-not $agent) {
    $agentOut = Join-Path $LogDir "argo-realtime-agent.out.log"
    $agentErr = Join-Path $LogDir "argo-realtime-agent.err.log"
    Start-Process `
        -FilePath $Python `
        -ArgumentList @($AgentFile, "connect", "--room", $Room, "--participant-identity", $AgentIdentity, "--log-level", "info") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $agentOut `
        -RedirectStandardError $agentErr `
        -WindowStyle Hidden `
        -PassThru | Out-Null
    Start-Sleep -Milliseconds 900
}

$serverStatus = if (Test-TcpPort -HostName "127.0.0.1" -Port 7880) { "ready" } else { "offline" }
$agentStatus = if (Get-AgentProcess) { "ready" } else { "offline" }

Write-Host "LiveKit server: $serverStatus"
Write-Host "ARGO realtime agent: $agentStatus"
Write-Host "Voice UI: http://localhost:8000/v2"
