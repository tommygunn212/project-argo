#!/usr/bin/env pwsh
<#
.SYNOPSIS
    ARGO One-Click Installer for Windows
.DESCRIPTION
    Downloads and installs everything needed to run ARGO:
    - Checks/installs Python 3.11
    - Checks/installs Ollama
    - Creates virtual environment
    - Installs Python dependencies
    - Pulls LLM model
    - Creates desktop shortcut
.EXAMPLE
    irm https://raw.githubusercontent.com/tommygunn212/project-argo/main/install.ps1 | iex
.NOTES
    Run as Administrator for best results
#>

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Faster downloads

# ============================================================================
# CONFIGURATION
# ============================================================================
$ARGO_VERSION = "1.6.24"
$REPO_URL = "https://github.com/tommygunn212/project-argo"
$REPO_BRANCH = "audio-reset-phase0"
$INSTALL_DIR = "$env:USERPROFILE\argo"
$PYTHON_MIN_VERSION = [Version]"3.10.0"
$OLLAMA_MODEL = "qwen2.5:3b"

# ============================================================================
# HELPERS
# ============================================================================
function Write-Step { param($msg) Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Write-OK { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "    $msg" -ForegroundColor Gray }

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PythonVersion {
    try {
        $output = python --version 2>&1
        if ($output -match "Python (\d+\.\d+\.\d+)") {
            return [Version]$Matches[1]
        }
    } catch {}
    return $null
}

function Test-Command { param($cmd) return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# ============================================================================
# BANNER
# ============================================================================
Clear-Host
Write-Host ""
Write-Host "  █████╗ ██████╗  ██████╗  ██████╗ " -ForegroundColor Cyan
Write-Host " ██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗" -ForegroundColor Cyan
Write-Host " ███████║██████╔╝██║  ███╗██║   ██║" -ForegroundColor Cyan
Write-Host " ██╔══██║██╔══██╗██║   ██║██║   ██║" -ForegroundColor Cyan
Write-Host " ██║  ██║██║  ██║╚██████╔╝╚██████╔╝" -ForegroundColor Cyan
Write-Host " ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ " -ForegroundColor Cyan
Write-Host ""
Write-Host "  One-Click Installer v$ARGO_VERSION" -ForegroundColor DarkGray
Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Admin)) {
    Write-Warn "Not running as Administrator - some features may require elevation"
}

# ============================================================================
# STEP 1: CHECK PYTHON
# ============================================================================
Write-Step "Checking Python installation..."

$pythonVersion = Get-PythonVersion
if ($pythonVersion -and $pythonVersion -ge $PYTHON_MIN_VERSION) {
    Write-OK "Python $pythonVersion found"
} else {
    Write-Warn "Python 3.10+ not found"
    Write-Info "Downloading Python installer..."
    
    $pythonInstaller = "$env:TEMP\python-installer.exe"
    $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    
    try {
        Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller -UseBasicParsing
        Write-Info "Running Python installer (this may take a minute)..."
        Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        
        $pythonVersion = Get-PythonVersion
        if ($pythonVersion) {
            Write-OK "Python $pythonVersion installed"
        } else {
            Write-Err "Python installation failed - please install manually from python.org"
            exit 1
        }
    } catch {
        Write-Err "Failed to download Python: $_"
        Write-Info "Please install Python 3.11 manually from https://www.python.org/downloads/"
        exit 1
    }
}

# ============================================================================
# STEP 2: CHECK OLLAMA
# ============================================================================
Write-Step "Checking Ollama installation..."

if (Test-Command "ollama") {
    Write-OK "Ollama found"
} else {
    Write-Warn "Ollama not found"
    Write-Info "Downloading Ollama installer..."
    
    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"
    $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
    
    try {
        Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaInstaller -UseBasicParsing
        Write-Info "Running Ollama installer..."
        Start-Process -FilePath $ollamaInstaller -ArgumentList "/S" -Wait
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        
        # Wait for Ollama to be available
        Start-Sleep -Seconds 3
        
        if (Test-Command "ollama") {
            Write-OK "Ollama installed"
        } else {
            Write-Warn "Ollama installed but not in PATH - may need to restart terminal"
        }
    } catch {
        Write-Err "Failed to download Ollama: $_"
        Write-Info "Please install Ollama manually from https://ollama.com/download"
        exit 1
    }
}

# ============================================================================
# STEP 3: DOWNLOAD ARGO
# ============================================================================
Write-Step "Downloading ARGO source code..."

if (Test-Path $INSTALL_DIR) {
    Write-Info "Existing installation found at $INSTALL_DIR"
    $response = Read-Host "    Overwrite? (y/N)"
    if ($response -ne "y" -and $response -ne "Y") {
        Write-Info "Keeping existing installation"
    } else {
        Remove-Item -Recurse -Force $INSTALL_DIR
    }
}

if (-not (Test-Path $INSTALL_DIR)) {
    if (Test-Command "git") {
        Write-Info "Cloning repository..."
        git clone --branch $REPO_BRANCH --depth 1 $REPO_URL $INSTALL_DIR 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Repository cloned"
        } else {
            Write-Err "Git clone failed"
            exit 1
        }
    } else {
        Write-Info "Git not found, downloading ZIP..."
        $zipUrl = "$REPO_URL/archive/refs/heads/$REPO_BRANCH.zip"
        $zipPath = "$env:TEMP\argo-source.zip"
        
        try {
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
            Write-Info "Extracting..."
            Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force
            Move-Item "$env:TEMP\project-argo-$REPO_BRANCH" $INSTALL_DIR
            Remove-Item $zipPath
            Write-OK "Source code downloaded"
        } catch {
            Write-Err "Failed to download: $_"
            exit 1
        }
    }
}

# ============================================================================
# STEP 4: CREATE VIRTUAL ENVIRONMENT
# ============================================================================
Write-Step "Creating Python virtual environment..."

Push-Location $INSTALL_DIR
try {
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Virtual environment created"
        } else {
            Write-Err "Failed to create virtual environment"
            exit 1
        }
    } else {
        Write-OK "Virtual environment already exists"
    }
} finally {
    Pop-Location
}

# ============================================================================
# STEP 5: INSTALL DEPENDENCIES
# ============================================================================
Write-Step "Installing Python dependencies (this may take a few minutes)..."

Push-Location $INSTALL_DIR
try {
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
    & .\.venv\Scripts\pip.exe install -r requirements.txt -q
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Dependencies installed"
    } else {
        Write-Err "Failed to install dependencies"
        exit 1
    }
} finally {
    Pop-Location
}

# ============================================================================
# STEP 6: PULL OLLAMA MODEL
# ============================================================================
Write-Step "Pulling LLM model ($OLLAMA_MODEL)..."

# Start Ollama if not running
$ollamaProcess = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    Write-Info "Starting Ollama service..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

try {
    Write-Info "Downloading model (this may take 5-10 minutes on first run)..."
    ollama pull $OLLAMA_MODEL 2>&1 | ForEach-Object { Write-Info $_ }
    Write-OK "Model ready"
} catch {
    Write-Warn "Could not pull model - you may need to run 'ollama pull $OLLAMA_MODEL' manually"
}

# ============================================================================
# STEP 7: CREATE CONFIG FILE
# ============================================================================
Write-Step "Creating configuration..."

$configPath = "$INSTALL_DIR\config.json"
if (-not (Test-Path $configPath)) {
    $config = @{
        audio = @{
            input_device_index = $null
            output_device_index = $null
            always_listen = $true
        }
        session = @{
            turn_limit = 6
        }
        personality = @{
            default = "tommy_gunn"
        }
    } | ConvertTo-Json -Depth 3
    
    Set-Content -Path $configPath -Value $config
    Write-OK "Default config created"
    Write-Warn "You may need to set audio device indices in config.json"
} else {
    Write-OK "Config file already exists"
}

# ============================================================================
# STEP 8: CREATE SHORTCUTS
# ============================================================================
Write-Step "Creating shortcuts..."

# Desktop shortcut
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = "$desktopPath\ARGO.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoExit -Command `"cd '$INSTALL_DIR'; .\.venv\Scripts\Activate.ps1; python main.py`""
$shortcut.WorkingDirectory = $INSTALL_DIR
$shortcut.Description = "Launch ARGO Voice Assistant"
$shortcut.Save()

Write-OK "Desktop shortcut created"

# Start menu shortcut
$startMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
$startShortcut = "$startMenuPath\ARGO.lnk"
$shortcut2 = $WshShell.CreateShortcut($startShortcut)
$shortcut2.TargetPath = "powershell.exe"
$shortcut2.Arguments = "-NoExit -Command `"cd '$INSTALL_DIR'; .\.venv\Scripts\Activate.ps1; python main.py`""
$shortcut2.WorkingDirectory = $INSTALL_DIR
$shortcut2.Description = "Launch ARGO Voice Assistant"
$shortcut2.Save()

Write-OK "Start menu shortcut created"

# ============================================================================
# STEP 9: CREATE LAUNCHER SCRIPT
# ============================================================================
$launcherPath = "$INSTALL_DIR\start_argo.ps1"
$launcherContent = @'
# ARGO Launcher
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# Start Ollama if not running
$ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Starting Ollama..." -ForegroundColor Cyan
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

# Activate venv and run
Write-Host "Starting ARGO..." -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1
python main.py

Pop-Location
'@

Set-Content -Path $launcherPath -Value $launcherContent
Write-OK "Launcher script created"

# ============================================================================
# COMPLETE
# ============================================================================
Write-Host ""
Write-Host "  ═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ ARGO Installation Complete!" -ForegroundColor Green
Write-Host "  ═══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Installation path: $INSTALL_DIR" -ForegroundColor Gray
Write-Host ""
Write-Host "  To start ARGO:" -ForegroundColor White
Write-Host "    • Double-click the ARGO shortcut on your desktop" -ForegroundColor Gray
Write-Host "    • Or run: $INSTALL_DIR\start_argo.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "  First-time setup:" -ForegroundColor Yellow
Write-Host "    1. Open $INSTALL_DIR\config.json" -ForegroundColor Gray
Write-Host "    2. Set your audio device indices (run 'python -c `"import sounddevice; print(sounddevice.query_devices())`"' to list)" -ForegroundColor Gray
Write-Host ""
Write-Host "  UI Dashboard: http://localhost:8000" -ForegroundColor Cyan
Write-Host ""

# Offer to run audio device check
$response = Read-Host "Would you like to see your audio devices now? (Y/n)"
if ($response -ne "n" -and $response -ne "N") {
    Push-Location $INSTALL_DIR
    & .\.venv\Scripts\python.exe -c "import sounddevice as sd; print(); print('Available Audio Devices:'); print('=' * 60); devices = sd.query_devices(); [print(f'{i:2}: {d[\"name\"]}') for i, d in enumerate(devices)]"
    Pop-Location
    Write-Host ""
    Write-Host "Set input_device_index and output_device_index in config.json" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
