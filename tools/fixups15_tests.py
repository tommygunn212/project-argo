"""Align test_zombie_guard.py with the report-only policy wording."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "tests" / "test_zombie_guard.py"
s = io.open(p, encoding="utf-8").read()
old = '''    text = str(raised.value)
    assert "2 orphaned worker" in text and "4242" in text and "4343" in text
    assert "start_argo_stack" in text'''
new = '''    text = str(raised.value)
    assert "2 parentless python process" in text and "4242" in text and "4343" in text
    assert "Nothing has been stopped" in text
    assert "-CleanOrphans" in text'''
assert old in s; s = s.replace(old, new, 1)
old2 = '''    monkeypatch.setattr(G, "zombie_workers", lambda: [
        {"pid": 4242, "started": "2026-09-13 16:47:03", "cmdline": "python -c spawn_main"},
        {"pid": 4343, "started": "2026-09-14 02:01:47", "cmdline": "python -c spawn_main"},
    ])'''
new2 = '''    monkeypatch.setattr(G, "zombie_workers", lambda: [
        {"pid": 4242, "started": "2026-09-13 16:47:03", "cmdline": "python -c spawn_main", "confirmed": True},
        {"pid": 4343, "started": "2026-09-14 02:01:47", "cmdline": "python -c spawn_main", "confirmed": False},
    ])'''
assert old2 in s; s = s.replace(old2, new2, 1)
io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s); print("test_zombie_guard aligned")
