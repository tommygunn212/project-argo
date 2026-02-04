<#
.SYNOPSIS
    ARGO Voice Assistant - Fresh Installation Script
.DESCRIPTION
    Installs ARGO on a fresh Windows machine:
    - Clones repository (or uses existing)
    - Creates Python virtual environment
    - Installs all pip dependencies
    - Downloads Piper TTS binary + voice
    - Creates desktop shortcut
.NOTES
    Run as: powershell -ExecutionPolicy Bypass -File install_argo.ps1
#>

param(
    [string]$InstallPath = "$env:LOCALAPPDATA\ARGO",
    [string]$RepoUrl = "https://github.com/tommygunn212/project-argo.git",
    [string]$Branch = "audio-reset-phase0"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "`n=== $msg ===" -ForegroundColor Cyan
}

function Write-Success($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "[!] $msg" -ForegroundColor Yellow
}

function Write-Fail($msg) {
    Write-Host "[X] $msg" -ForegroundColor Red
}

# ============================================================================
# 1) CHECK PYTHON
# ============================================================================
Write-Step "Checking Python installation"

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-Success "Found $ver ($cmd)"
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Fail "Python 3.10+ required but not found."
    Write-Host "Download from: https://www.python.org/downloads/"
    exit 1
}

# ============================================================================
# 2) CHECK GIT
# ============================================================================
Write-Step "Checking Git installation"

try {
    $gitVer = git --version
    Write-Success "Found $gitVer"
} catch {
    Write-Fail "Git not found."
    Write-Host "Download from: https://git-scm.com/download/win"
    exit 1
}

# ============================================================================
# 3) CLONE OR UPDATE REPO
# ============================================================================
Write-Step "Setting up ARGO repository"

if (Test-Path "$InstallPath\.git") {
    Write-Host "Existing installation found. Updating..."
    Push-Location $InstallPath
    git fetch origin
    git checkout $Branch
    git pull origin $Branch
    Pop-Location
    Write-Success "Repository updated"
} else {
    Write-Host "Cloning repository to $InstallPath..."
    git clone --branch $Branch $RepoUrl $InstallPath
    Write-Success "Repository cloned"
}

Set-Location $InstallPath

# ============================================================================
# 4) CREATE VIRTUAL ENVIRONMENT
# ============================================================================
Write-Step "Setting up Python virtual environment"

$venvPath = Join-Path $InstallPath ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$venvPip = Join-Path $venvPath "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    & $pythonCmd -m venv $venvPath
    Write-Success "Virtual environment created"
} else {
    Write-Success "Virtual environment exists"
}

# ============================================================================
# 5) INSTALL PYTHON DEPENDENCIES
# ============================================================================
Write-Step "Installing Python packages"

& $venvPip install --upgrade pip wheel setuptools
& $venvPip install -r requirements.txt
& $venvPip install tzdata  # Windows timezone data

Write-Success "Python packages installed"

# ============================================================================
# 6) DOWNLOAD PIPER TTS
# ============================================================================
Write-Step "Setting up Piper TTS"

$piperDir = Join-Path $InstallPath "piper"
$piperExe = Join-Path $piperDir "piper.exe"
$voicesDir = Join-Path $InstallPath "voices"

# Piper binary
if (-not (Test-Path $piperExe)) {
    Write-Host "Downloading Piper TTS..."
    $piperUrl = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
    $piperZip = Join-Path $env:TEMP "piper.zip"
    
    Invoke-WebRequest -Uri $piperUrl -OutFile $piperZip
    Expand-Archive -Path $piperZip -DestinationPath $InstallPath -Force
    Remove-Item $piperZip
    Write-Success "Piper TTS downloaded"
} else {
    Write-Success "Piper TTS exists"
}

# Voice model (ryan - medium quality)
if (-not (Test-Path $voicesDir)) {
    New-Item -ItemType Directory -Path $voicesDir | Out-Null
}

$voiceModel = Join-Path $voicesDir "en_US-ryan-medium.onnx"
$voiceConfig = Join-Path $voicesDir "en_US-ryan-medium.onnx.json"

if (-not (Test-Path $voiceModel)) {
    Write-Host "Downloading Ryan voice model..."
    $modelUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx"
    $configUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json"
    
    Invoke-WebRequest -Uri $modelUrl -OutFile $voiceModel
    Invoke-WebRequest -Uri $configUrl -OutFile $voiceConfig
    Write-Success "Voice model downloaded"
} else {
    Write-Success "Voice model exists"
}

# ============================================================================
# 7) CREATE CONFIG FROM TEMPLATE
# ============================================================================
Write-Step "Checking configuration"

$configFile = Join-Path $InstallPath "config.json"
$templateFile = Join-Path $InstallPath "config.json.template"

if (-not (Test-Path $configFile)) {
    if (Test-Path $templateFile) {
        Copy-Item $templateFile $configFile
        Write-Warn "Created config.json from template - you may need to edit it"
    } else {
        Write-Warn "No config template found - using defaults"
    }
} else {
    Write-Success "config.json exists"
}

# ============================================================================
# 8) CREATE DESKTOP SHORTCUT
# ============================================================================
Write-Step "Creating desktop shortcut"

$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "ARGO.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -Command `"& '$venvPath\Scripts\Activate.ps1'; python main.py`""
$shortcut.WorkingDirectory = $InstallPath
$shortcut.Description = "ARGO Voice Assistant"
$shortcut.Save()

Write-Success "Desktop shortcut created"

# ============================================================================
# 9) DISPLAY VERSION AND SUMMARY
# ============================================================================
Write-Step "Installation Complete!"

$versionFile = Join-Path $InstallPath "VERSION"
if (Test-Path $versionFile) {
    $version = Get-Content $versionFile -Raw
    Write-Host "`nARGO Version: $version" -ForegroundColor White
}

Write-Host "`nInstall location: $InstallPath" -ForegroundColor White
Write-Host "`nTo start ARGO:" -ForegroundColor White
Write-Host "  1. Double-click the ARGO shortcut on your desktop" -ForegroundColor Gray
Write-Host "  2. Or run: cd $InstallPath && .\.venv\Scripts\Activate.ps1 && python main.py" -ForegroundColor Gray

Write-Host "`nOptional setup:" -ForegroundColor Yellow
Write-Host "  - Edit config.json for API keys (Porcupine, OpenAI)" -ForegroundColor Gray
Write-Host "  - Install Ollama for local LLM: https://ollama.ai" -ForegroundColor Gray

Write-Host ""
