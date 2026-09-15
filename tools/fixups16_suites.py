import io
from pathlib import Path
p = Path(__file__).resolve().parents[1] / "tools" / "prove_voice.py"
s = io.open(p, encoding="utf-8").read()
old = '    "tests/test_deep_think.py",\n]'
new = ('    "tests/test_deep_think.py",\n    "tests/test_runtime_guard.py",\n'
       '    "tests/test_zombie_guard.py",\n    "tests/test_orphan_policy.py",\n]')
if "test_orphan_policy" not in s:
    assert old in s; s = s.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s); print("suites present:", "test_orphan_policy" in s)
