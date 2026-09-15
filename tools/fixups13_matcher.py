import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "tools" / "prove_voice.py"
s = io.open(p, encoding="utf-8").read()
changes = 0
for old, new in [
    ('    joined = "PASS - agent" in output', '    joined = "PASS - a real session started" in output'),
    ('        if line.startswith("PASS - agent") or line.startswith("FAIL - no agent"):',
     '        if line.startswith("PASS - a real session") or line.startswith("FAIL - no session"):'),
]:
    if new in s:
        continue
    assert old in s, old
    s = s.replace(old, new, 1); changes += 1
io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s)
print(f"matcher: {changes} change(s) applied; present={'PASS - a real session started' in s}")
