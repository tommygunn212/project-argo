"""Move the remaining tests onto the directive-style briefs."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []


def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")


patch("tests/test_persona_briefs.py",
'''    for must in ("warm", "friend", "dry wit", "direct", "curious", "weakness", "plainly"):
        assert must in text, f"argo brief lost '{must}'"
    for never in ("assistant", "chatbot", "helpful ai"):
        assert never not in text''',
'''    # Directives, not adjectives: each of these is a behaviour you could check
    # against a transcript.
    for must in ("friend", "contractions", "dry aside", "hole", "assumption", "one level deeper"):
        assert must in text, f"argo brief lost '{must}'"
    for never in ("chatbot", "helpful ai"):
        assert never not in text
    assert "not a service desk" in text''',
"argo brief is directive", marker="not a service desk")

patch("tests/test_persona_briefs.py",
'''    text = P.compose_instructions("argo")
    assert text.count("\\n\\n") == 3
    assert "get_pc_specs" not in text and "list_folder" not in text, "tool manual leaked into the brief"''',
'''    text = P.compose_instructions("argo")
    # Checked by reconstruction rather than by counting blank lines: the
    # contract has paragraphs of its own now.
    expected = "\\n\\n".join([P.CONVERSATION_CONTRACT, P.get("argo").block,
                             P.DEEP_THINK_POLICY, P.TOOL_POLICY])
    assert text == expected
    assert "get_pc_specs" not in text and "list_folder" not in text, "tool manual leaked into the brief"''',
"four parts by reconstruction", marker="expected = ")

patch("tests/test_persona_briefs.py",
'''def test_the_contract_bans_the_runups_the_first_mic_run_produced():''',
'''def test_the_hardest_rules_come_first():
    """Realtime models weight the top of the instruction, and the first
    version buried the prohibitions ~2000 characters in - where the model
    ignored them. The first-sentence rule and the silence rule lead now."""
    assert "THE FIRST THING YOU SAY IS THE ANSWER" in P.CONVERSATION_CONTRACT[:700]
    assert "SAY NOTHING AT ALL" in P.CONVERSATION_CONTRACT[:1500]


def test_briefs_are_written_as_directives_not_descriptions():
    """The failure this rewrite fixes: trait adjectives do not steer a
    realtime model. Every brief must tell it what to DO."""
    for name in P.SELECTABLE:
        b = P.get(name)
        text = (b.voice + " " + b.collaboration).lower()
        assert any(v in text for v in ("say", "open with", "answer", "ask", "keep", "never", "do not", "volunteer")), name


def test_the_contract_bans_the_runups_the_first_mic_run_produced():''',
"hardest rules first + directive check", marker="def test_the_hardest_rules_come_first")

patch("tests/test_realtime_personality.py",
'''    assert "Voice and manner:" not in composed''',
'''    assert "WHO YOU ARE TODAY:" not in composed''',
"unknown persona adds no block", marker='assert "WHO YOU ARE TODAY:" not in composed')

patch("tests/test_realtime_personality.py",
'''    assert "Voice and manner:" in composed''',
'''    assert "WHO YOU ARE TODAY:" in composed''',
"known persona adds a block", marker='assert "WHO YOU ARE TODAY:" in composed')

print("\n".join(log))
import ast
for rel in ("tests/test_persona_briefs.py", "tests/test_realtime_personality.py"):
    ast.parse(io.open(ROOT / rel, encoding="utf-8").read())
print("parse ok")
