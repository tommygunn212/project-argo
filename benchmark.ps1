#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Benchmark JARVIS wrapper performance with time measurements.
#>

Write-Host "=== JARVIS Performance Benchmark ===" -ForegroundColor Cyan
Write-Host ""

# Test cases
$tests = @(
    @{ name = "Short query"; input = "What is 2+2?" },
    @{ name = "Medium query"; input = "Explain photosynthesis" },
    @{ name = "Long-form query"; input = "Explain in detail how machine learning works" }
)

$results = @()

foreach ($test in $tests) {
    Write-Host "Test: $($test.name)" -ForegroundColor Yellow
    Write-Host "Input: `"$($test.input)`"" -ForegroundColor Gray
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    
    # Run JARVIS
    $output = & python wrapper\jarvis.py $test.input 2>&1
    
    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.TotalSeconds
    
    Write-Host "Time: $([Math]::Round($elapsed, 2))s" -ForegroundColor Green
    Write-Host "Output preview: $($output[0..50] -join '`n')" -ForegroundColor White
    Write-Host ""
    
    $results += @{
        name = $test.name
        time = $elapsed
        outputLines = ($output | Measure-Object -Line).Lines
    }
}

# Summary
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host ""
foreach ($result in $results) {
    $timeStr = "$([Math]::Round($result.time, 2))s".PadRight(8)
    Write-Host "$($result.name.PadRight(20)) : $timeStr ($($result.outputLines) lines)" -ForegroundColor White
}

$totalTime = ($results | Measure-Object -Property time -Sum).Sum
Write-Host ""
Write-Host "Total time: $([Math]::Round($totalTime, 2))s" -ForegroundColor Cyan
