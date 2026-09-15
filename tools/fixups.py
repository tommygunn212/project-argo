"""Apply the fixes the first proof run earned. Run once, from I:\\argo."""
import io, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
done = []

def patch(rel, old, new, label):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if new in s:
        done.append(f"SKIP (already applied) {label}")
        return
    assert old in s, f"ANCHOR NOT FOUND in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    done.append(f"OK   {label}")

# 1. SAM is a credential, not merely a Windows location. My test asserted the
#    wrong refusal: is_secret fires first, and that is the correct order - a
#    voice assistant reading the SAM hive aloud is the worse outcome.
patch("tests/test_path_containment.py",
'''@pytest.mark.parametrize("path", [
    r"C:\\Windows\\System32\\config\\SAM",
    r"C:\\Program Files\\App\\licence.key.txt",
    r"C:\\ProgramData\\secrets\\thing.dat",
])
def test_system_locations_are_refused_for_reading(path):''',
'''@pytest.mark.parametrize("path", [
    r"C:\\Windows\\System32\\drivers\\etc\\hosts",
    r"C:\\Program Files\\App\\readme.txt",
    r"C:\\ProgramData\\secrets\\thing.dat",
])
def test_system_locations_are_refused_for_reading(path):''',
"path containment: system read cases")

patch("tests/test_path_containment.py",
'''def test_narrowed_roots_still_answer_out_of_scope_first(monkeypatch):''',
'''@pytest.mark.parametrize("path", [
    r"C:\\Windows\\System32\\config\\SAM",
    r"C:\\Program Files\\App\\licence.key",
])
def test_a_system_file_that_is_also_a_credential_is_refused_as_a_secret(path):
    """Order matters: "I won't read a credential aloud" is the more useful
    refusal than "that folder belongs to Windows", and it is the one that
    still applies if the folder rules are ever widened."""
    assert FS.check_read(Path(path))["error"] == "secret_file"


def test_narrowed_roots_still_answer_out_of_scope_first(monkeypatch):''',
"path containment: secret-beats-location test")

# 2. The old turn-taking test pinned hair-trigger values and a phrase the
#    instructions no longer use. Both were deliberate changes, so the test
#    has to move with them - and say why, or the next person reverts it.
patch("tests/test_livekit_config.py",
'''    assert cfg.min_interruption_duration == 0.08
    assert cfg.false_interruption_timeout == 0.22
    # Interruption stays fast, but reply LENGTH is no longer capped: the
    # instructions used to say "answer in one short sentence by default",
    # which is what made ARGO sound clipped next to ChatGPT voice mode.
    assert "one short sentence" not in cfg.instructions
    assert "as long as the question deserves" in cfg.instructions''',
'''    # These used to be 0.08s / 0.22s - hair-trigger. That is what made ARGO
    # cut in on a cough, on the AC, and on her own speaker bleeding back into
    # the Brio. Generic speech now has to be sustained; a decisive "stop" gets
    # a separate fast path instead (see urgent_interrupt_phrases), so nothing
    # urgent pays for this.
    assert cfg.min_interruption_duration >= 0.3
    assert cfg.false_interruption_timeout >= 1.0
    assert cfg.min_interruption_words >= 2
    assert "stop" in cfg.urgent_interrupt_phrases

    # Reply LENGTH stays uncapped: the instructions used to say "answer in one
    # short sentence by default", which is what made ARGO sound clipped next
    # to ChatGPT voice mode.
    assert "one short sentence" not in cfg.instructions
    assert "match his length" in cfg.instructions.lower()''',
"livekit config: turn-taking defaults")

# 3. compose_realtime_instructions now assembles the tool and deep-think
#    briefs too, so "unchanged" is no longer the right claim. What must still
#    hold is that an unknown persona adds no MANNER.
patch("tests/test_realtime_personality.py",
'''def test_compose_with_unknown_persona_returns_base_unchanged():
    assert livekit_config.compose_realtime_instructions("BASE.", "nope") == "BASE."''',
'''def test_compose_with_unknown_persona_adds_no_manner():
    """The briefs are always assembled; an unknown persona just contributes
    no voice of its own."""
    composed = livekit_config.compose_realtime_instructions("BASE.", "nope")
    assert composed.startswith("BASE.")
    assert "Voice and manner:" not in composed


def test_compose_with_a_known_persona_adds_manner():
    composed = livekit_config.compose_realtime_instructions("BASE.", "argo")
    assert composed.startswith("BASE.")
    assert "Voice and manner:" in composed''',
"realtime personality: unknown persona")

# 4. My own check matched the phrase inside "Do not repeat his question back".
patch("tools/prove_voice.py",
'''    banned = {
        "repeats the question": "repeat his question",
        "canned acknowledgement": "great question",
        "narrates internal steps": "explain what you are doing",
    }
    present = [label for label, phrase in banned.items() if phrase in text]''',
'''    # Each phrase must appear ONLY inside a prohibition. Matching the bare
    # phrase flagged "Do not repeat his question back" as asking for the very
    # thing it forbids.
    banned = {
        "repeats the question": "repeat his question",
        "canned acknowledgement": "great question",
        "narrates internal steps": "narrate what you are about to do",
    }
    present = [
        label for label, phrase in banned.items()
        if phrase in text and not re.search(r"do not [^.]{0,40}" + re.escape(phrase), text)
    ]''',
"prove_voice: instruction check false positive")

# 5. The UI's persisted personality outranks config.json, so config alone
#    never moved her off tommy_gunn.
personality_file = ROOT / "runtime" / "voice_personality.json"
from datetime import datetime, timezone
personality_file.write_text(json.dumps(
    {"personality": "argo", "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2),
    encoding="utf-8")
done.append("OK   runtime/voice_personality.json -> argo")

# 6. On Windows the key lives in the User environment, not in .env, so any
#    shell started before it was set cannot see it. Read it back explicitly
#    rather than reporting a missing key that is plainly there.
patch("tools/realtime_preflight.py",
'''load_dotenv(ROOT / ".env")''',
'''load_dotenv(ROOT / ".env")


def _ensure_api_key() -> None:
    """Windows keeps OPENAI_API_KEY in the User environment here, not in .env.

    A process started before that variable was set does not inherit it, which
    looks exactly like a missing key. Read it back from the registry scope
    before concluding anything.
    """
    if os.getenv("OPENAI_API_KEY"):
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "OPENAI_API_KEY")
        if value:
            os.environ["OPENAI_API_KEY"] = value
    except Exception:
        pass


_ensure_api_key()''',
"preflight: read the User-scope API key")

print("\\n".join(done))
