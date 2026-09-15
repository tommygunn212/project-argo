"""Apply the per-sentence banned check, and move three tests onto the
directive-style briefs.

The check must judge a whole sentence, not a 90-character lookback: the
contract's prohibition is one long sentence - "Never begin with: 'a', 'b',
'c', ..." - and the later items sat outside the window, so the check flagged
the very list that bans them.
"""
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


patch("core/persona_briefs.py",
'''def find_banned(text: str) -> list[str]:
    """Phrases a persona brief must not put in the model's mouth. A brief may
    MENTION a phrase only inside a prohibition ('never say ...')."""
    lowered = text.lower()
    hits = []
    for phrase in BANNED_RUNUPS + BANNED_CATCHPHRASES:
        for m in re.finditer(re.escape(phrase), lowered):
            window = lowered[max(0, m.start() - 90):m.start()]
            if not re.search(r"(never|no |not |do not|don't|without|begin with:)[^.]{0,85}$", window):
                hits.append(phrase)
                break
    return hits''',
'''_NEGATION = re.compile(r"\\b(never|not|no|don't|do not|without|avoid|delete any)\\b")


def _sentences(text: str) -> list[str]:
    """Split on sentence ends, keeping a quoted list like "never begin with:
    'a', 'b', 'c'" as ONE unit - the prohibition and its items belong
    together, and splitting them is what made this check cry wolf."""
    return [s for s in re.split(r"(?<=[.!?])\\s+(?=[A-Z])|\\n\\n", text) if s.strip()]


def find_banned(text: str) -> list[str]:
    """Phrases a persona brief must not put in the model's mouth.

    A phrase is fine when it appears inside a PROHIBITION - the contract has
    to be able to name what it forbids. So the unit of judgement is the whole
    sentence: if the sentence negates, every phrase in it is being banned,
    not asked for.
    """
    hits: list[str] = []
    sentences = [s.lower() for s in _sentences(text)]
    for phrase in BANNED_RUNUPS + BANNED_CATCHPHRASES:
        for lowered in sentences:
            if phrase in lowered and not _NEGATION.search(lowered):
                hits.append(phrase)
                break
    return hits''',
"persona_briefs: per-sentence banned check", marker="_NEGATION = re.compile")

# --- tests follow the directive rewrite -------------------------------------------
patch("tests/test_persona_briefs.py",
'''def test_argo_reads_as_a_collaborator_not_an_assistant():
    b = P.get("argo")
    text = (b.voice + " " + b.collaboration).lower()
    for must in ("warm", "friend", "dry wit", "direct", "curious", "weakness", "plainly"):
        assert must in text, f"argo brief lost '{must}'"
    for never in ("assistant", "chatbot", "helpful ai"):
        assert never not in text''',
'''def test_argo_reads_as_a_collaborator_not_an_assistant():
    b = P.get("argo")
    text = (b.voice + " " + b.collaboration).lower()
    # Directives, not adjectives: each of these is a behaviour you could check
    # against a transcript.
    for must in ("friend", "contractions", "dry aside", "hole", "assumption", "one level deeper"):
        assert must in text, f"argo brief lost '{must}'"
    for never in ("chatbot", "helpful ai", "service desk is what you are"):
        assert never not in text
    assert "not a service desk" in text''',
"test: argo brief is directive")

patch("tests/test_persona_briefs.py",
'''def test_nothing_else_is_stacked_on_top():
    """Contract + persona + deep-think policy + tool policy. Four parts, no more."""
    text = P.compose_instructions("argo")
    assert text.count("\\n\\n") == 3
    assert "get_pc_specs" not in text and "list_folder" not in text, "tool manual leaked into the brief"''',
'''def test_nothing_else_is_stacked_on_top():
    """Contract + persona + deep-think policy + tool policy. Four parts, no more.

    Checked by reconstruction rather than by counting blank lines: the
    contract has paragraphs of its own now.
    """
    text = P.compose_instructions("argo")
    expected = "\\n\\n".join([P.CONVERSATION_CONTRACT, P.get("argo").block,
                             P.DEEP_THINK_POLICY, P.TOOL_POLICY])
    assert text == expected
    assert "get_pc_specs" not in text and "list_folder" not in text, "tool manual leaked into the brief"''',
"test: four parts by reconstruction")

patch("tests/test_persona_briefs.py",
'''def test_the_contract_bans_the_runups_the_first_mic_run_produced():''',
'''def test_the_hardest_rules_come_first():
    """Realtime models weight the top of the instruction. The first-sentence
    rule and the silence rule have to be there, not buried at the bottom."""
    head = P.CONVERSATION_CONTRACT[:700].lower()
    assert "the first thing you say is the answer" in head
    assert "say nothing at all" in P.CONVERSATION_CONTRACT[:1400].lower()


def test_the_contract_bans_the_runups_the_first_mic_run_produced():''',
"test: hardest rules first")

print("\n".join(log))
import ast
ast.parse(io.open(ROOT / "core/persona_briefs.py", encoding="utf-8").read())
ast.parse(io.open(ROOT / "tests/test_persona_briefs.py", encoding="utf-8").read())
print("parse ok")
