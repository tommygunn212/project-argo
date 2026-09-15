"""A Smooth Voice VOICE selector, server-side, alongside the personality one.

Tommy switched the Text-to-Speech dropdown to Alloy and kept hearing the same
voice. Correct behaviour: that dropdown is the classic fallback's. Smooth
Voice's voice was `marin`, pinned in config.json, with no control anywhere in
the UI - so every lever he could actually reach was the wrong one.

Same mechanism as personality: written to a file the worker reads at session
start, so it survives a restart and applies on the NEXT connection.
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

LK = "core/livekit_config.py"

# --- 1. the voices the realtime model actually accepts, and the handoff file -------
patch(LK,
'''VOICE_PERSONALITY_FILE = Path(__file__).resolve().parents[1] / "runtime" / "voice_personality.json"''',
'''VOICE_PERSONALITY_FILE = Path(__file__).resolve().parents[1] / "runtime" / "voice_personality.json"
# Same cross-process handoff as the personality, for the same reason: the
# worker is a separate process and in-memory runtime overrides never reach it.
REALTIME_VOICE_FILE = Path(__file__).resolve().parents[1] / "runtime" / "realtime_voice.json"

# What gpt-realtime will actually accept. Anything else is refused at the
# session level, which is a bad way to find out - so it is checked here.
REALTIME_VOICES = [
    ("marin", "Marin - warm, natural (default)"),
    ("cedar", "Cedar - warm, lower"),
    ("alloy", "Alloy - balanced, neutral"),
    ("ash", "Ash - clear, even"),
    ("ballad", "Ballad - soft, expressive"),
    ("coral", "Coral - bright, friendly"),
    ("echo", "Echo - crisp, measured"),
    ("sage", "Sage - calm, steady"),
    ("shimmer", "Shimmer - light, quick"),
    ("verse", "Verse - rich, narrative"),
]
REALTIME_VOICE_NAMES = [v for v, _ in REALTIME_VOICES]


def read_realtime_voice(config: Any | None = None) -> str:
    """Which voice the next realtime session speaks in.

    Precedence matches the personality: env override, then the UI selection
    persisted by main.py, then config.json, then marin.
    """
    env_value = (os.getenv("ARGO_REALTIME_VOICE") or "").strip()
    if env_value:
        return env_value
    try:
        import json

        raw = json.loads(REALTIME_VOICE_FILE.read_text(encoding="utf-8"))
        chosen = str(raw.get("voice", "")).strip().lower()
        if chosen in REALTIME_VOICE_NAMES:
            return chosen
    except FileNotFoundError:
        pass
    except Exception:
        pass
    cfg = config or get_config()
    return str(_env_or_config(cfg, "ARGO_REALTIME_VOICE", "livekit.voice", "marin") or "marin")


def write_realtime_voice(voice: str) -> None:
    """Persist the UI's voice selection for the next realtime session."""
    import json
    from datetime import datetime, timezone

    name = str(voice or "").strip().lower()
    if name not in REALTIME_VOICE_NAMES:
        raise ValueError(f"{voice!r} is not a gpt-realtime voice. "
                         f"Choose from: {', '.join(REALTIME_VOICE_NAMES)}")
    REALTIME_VOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"voice": name, "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = REALTIME_VOICE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(REALTIME_VOICE_FILE)''',
"livekit_config: realtime voice handoff", marker="REALTIME_VOICE_FILE")

# --- 2. the config reads it ---------------------------------------------------------
patch(LK,
'''        voice=_env_or_config(cfg, "ARGO_REALTIME_VOICE", "livekit.voice", "marin"),''',
'''        voice=read_realtime_voice(cfg),''',
"livekit_config: config uses the selected voice", marker="voice=read_realtime_voice(cfg),")

# --- 3. status offers the list -------------------------------------------------------
patch(LK,
'''        "personas": _persona_list(),''',
'''        "personas": _persona_list(),
        "voices": [{"name": v, "label": label} for v, label in REALTIME_VOICES],''',
"livekit_config: voices in status", marker='"voices": [{"name": v')

# --- 4. main.py persists the override ---------------------------------------------------
patch("main.py",
'''    if pipeline_ref and hasattr(pipeline_ref, "apply_runtime_tuning"):''',
'''    if key == "realtime_voice":
        # Smooth Voice's voice, not the classic pipeline's. Separate control,
        # separate file, same cross-process reason as the personality.
        try:
            from core.livekit_config import write_realtime_voice

            write_realtime_voice(str(value))
            log_event(f"REALTIME_VOICE_PERSISTED {value}", stage="ui")
        except Exception as exc:
            logger.exception("[OVERRIDE] Could not persist realtime voice")
            broadcast_msg("log", f"Voice not saved: {exc}")
    if pipeline_ref and hasattr(pipeline_ref, "apply_runtime_tuning"):''',
"main.py: realtime_voice override", marker="REALTIME_VOICE_PERSISTED")

print("\n".join(log))
import ast
for rel in (LK, "main.py"):
    ast.parse(io.open(ROOT / rel, encoding="utf-8").read())
print("parse ok")
