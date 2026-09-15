"""Move the three old assertions onto the new source of truth."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if new in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

patch("tests/test_livekit_config.py",
'''    assert "match his length" in cfg.instructions.lower()''',
'''    lowered = cfg.instructions.lower()
    assert "a casual thought gets a real but short reply" in lowered
    assert "not a cut-off" in lowered''',
"livekit_config: length expectation follows the contract")

s = io.open(ROOT / "tests/test_realtime_personality.py", encoding="utf-8").read()
import re
# style now comes from persona_briefs, and argo is selectable
s = s.replace('SELECTABLE = ["tommy_gunn", "jarvis", "tommy_mix", "rick", "claptrap", "plain"]',
              'SELECTABLE = ["argo", "tommy_gunn", "jarvis", "tommy_mix", "rick", "claptrap", "plain"]', 1)
s = s.replace('assert personas.get_voice_style("jarvis") in out',
              'from core.persona_briefs import get as _brief\n    assert _brief("jarvis").block in out', 1)
s = s.replace('assert personas.get_voice_style("claptrap") in cfg.instructions',
              'from core.persona_briefs import get as _brief\n    assert _brief("claptrap").block in cfg.instructions', 1)
io.open(ROOT / "tests/test_realtime_personality.py", "w", encoding="utf-8", newline="").write(s)
log.append("OK   realtime_personality: assert against persona_briefs")
print("\n".join(log))
