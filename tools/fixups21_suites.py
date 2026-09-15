import io
from pathlib import Path
p = Path(__file__).resolve().parents[1] / "tools" / "prove_voice.py"
s = io.open(p, encoding="utf-8").read()
old = '    "tests/test_orphan_policy.py",\n]'
new = ('    "tests/test_orphan_policy.py",\n    "tests/test_persona_briefs.py",\n'
       '    "tests/test_persona_reaches_session.py",\n    "tests/test_deep_think_persona.py",\n]')
if "test_persona_briefs" not in s:
    assert old in s; s = s.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s); print("suites:", "test_persona_briefs" in s)
