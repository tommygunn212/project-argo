#!/usr/bin/env pwsh
# Test interactive mode with piped input

$input = @"
What is 2+2?
Explain photosynthesis
exit
"@ | python wrapper\jarvis.py

Write-Host "✅ Interactive test completed" -ForegroundColor Green
