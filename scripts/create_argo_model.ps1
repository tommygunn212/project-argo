#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Create the ARGO model in Ollama from the Modelfile
#>

Write-Host "Building ARGO model..." -ForegroundColor Cyan
Write-Host ""

# Build the model
ollama create argo -f runtime\ollama\modelfiles\argo\Modelfile

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] ARGO model created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Test it with:" -ForegroundColor Yellow
    Write-Host '  ollama run argo "hello"' -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "[ERROR] Failed to create ARGO model" -ForegroundColor Red
    exit 1
}
