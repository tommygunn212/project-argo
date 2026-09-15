import io
from pathlib import Path
p = Path(__file__).resolve().parents[1] / "scripts" / "start_argo_stack.ps1"
s = io.open(p, encoding="utf-8").read()
old = '''Write-Host "Starting backend..."'''
new = '''# Keep the previous worker's last words. The restart used to overwrite
# worker.out.log, which is exactly where "did it drain, and how" was recorded.
foreach ($name in 'worker', 'main') {
    $cur = Join-Path $Logs "$name.out.log"; $err = Join-Path $Logs "$name.err.log"
    if (Test-Path $cur) { Move-Item $cur (Join-Path $Logs "$name.prev.out.log") -Force }
    if (Test-Path $err) { Move-Item $err (Join-Path $Logs "$name.prev.err.log") -Force }
}

Write-Host "Starting backend..."'''
if "prev.out.log" not in s:
    assert s.count(old) == 1; s = s.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(s)
print("rotation:", "prev.out.log" in s)
