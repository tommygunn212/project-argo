#!/usr/bin/env pwsh
<#
.SYNOPSIS
Setup script for Argo on Windows.
.DESCRIPTION
Creates virtual environment and installs dependencies.
.EXAMPLE
./setup.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "🔧 Argo Setup" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "Checking Python..." -ForegroundColor Gray
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Python not found. Install Python 3.9+ and try again." -ForegroundColor Red
    exit 1
}
Write-Host "✓ $pythonVersion" -ForegroundColor Green

# Create venv
Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Gray
if (Test-Path .venv) {
    Write-Host "  (venv already exists)" -ForegroundColor DarkGray
} else {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to create venv" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ venv created" -ForegroundColor Green
}

# Activate venv
Write-Host ""
Write-Host "Activating venv..." -ForegroundColor Gray
& .\.venv\Scripts\Activate.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to activate venv" -ForegroundColor Red
    exit 1
}
Write-Host "✓ venv activated" -ForegroundColor Green

# Install requirements
Write-Host ""
Write-Host "Installing requirements..." -ForegroundColor Gray
pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install requirements" -ForegroundColor Red
    exit 1
}
Write-Host "✓ requirements installed" -ForegroundColor Green

# Load profile
Write-Host ""
Write-Host "Loading PowerShell profile..." -ForegroundColor Gray
. $PROFILE
Write-Host "✓ profile loaded" -ForegroundColor Green

Write-Host ""
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Make sure Ollama is running: ollama serve"
Write-Host "  2. Start Argo: ai"
Write-Host ""
