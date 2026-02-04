<#
.SYNOPSIS
    ARGO Voice Assistant - Update Script
.DESCRIPTION
    Updates an existing ARGO installation:
    - Pulls latest code from repository
    - Updates Python dependencies
    - Shows changelog of new changes
.NOTES
    Run from ARGO directory or pass -InstallPath
#>

param(
    [string]$InstallPath = $PWD
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

# ============================================================================
# 1) VERIFY ARGO INSTALLATION
# ============================================================================
Write-Step "Verifying ARGO installation"

if (-not (Test-Path "$InstallPath\.git")) {
    Write-Host "Not an ARGO installation. Run install_argo.ps1 first." -ForegroundColor Red
    exit 1
}

Set-Location $InstallPath

$oldVersion = "unknown"
$versionFile = Join-Path $InstallPath "VERSION"
if (Test-Path $versionFile) {
    $oldVersion = (Get-Content $versionFile -Raw).Trim()
}

Write-Success "Found ARGO $oldVersion"

# ============================================================================
# 2) PULL LATEST CODE
# ============================================================================
Write-Step "Pulling latest changes"

# Stash any local changes
$stashNeeded = (git status --porcelain) -ne ""
if ($stashNeeded) {
    Write-Warn "Stashing local changes..."
    git stash push -m "update_argo auto-stash"
}

# Get current branch
$branch = git rev-parse --abbrev-ref HEAD

# Pull latest
git fetch origin
$behind = git rev-list --count "HEAD..origin/$branch"

if ($behind -eq 0) {
    Write-Host "Already up to date."
} else {
    Write-Host "Pulling $behind new commit(s)..."
    
    # Show what's coming
    Write-Host "`nChanges:" -ForegroundColor Yellow
    git log --oneline "HEAD..origin/$branch" | Select-Object -First 10
    
    git pull origin $branch
    Write-Success "Code updated"
}

# Restore stashed changes
if ($stashNeeded) {
    Write-Host "Restoring local changes..."
    git stash pop
}

# ============================================================================
# 3) UPDATE DEPENDENCIES
# ============================================================================
Write-Step "Updating Python packages"

$venvPip = Join-Path $InstallPath ".venv\Scripts\pip.exe"

if (Test-Path $venvPip) {
    & $venvPip install --upgrade pip wheel setuptools -q
    & $venvPip install -r requirements.txt -q
    Write-Success "Dependencies updated"
} else {
    Write-Warn "Virtual environment not found. Run install_argo.ps1"
}

# ============================================================================
# 4) SHOW VERSION CHANGE
# ============================================================================
Write-Step "Update Complete!"

$newVersion = "unknown"
if (Test-Path $versionFile) {
    $newVersion = (Get-Content $versionFile -Raw).Trim()
}

if ($oldVersion -ne $newVersion) {
    Write-Host "`nVersion: $oldVersion -> $newVersion" -ForegroundColor Green
} else {
    Write-Host "`nVersion: $newVersion" -ForegroundColor White
}

# Show recent changelog
$changelogFile = Join-Path $InstallPath "CHANGELOG.md"
if (Test-Path $changelogFile) {
    Write-Host "`nRecent changes:" -ForegroundColor Yellow
    Get-Content $changelogFile | Select-Object -First 15
}

Write-Host ""
