"""Three changes, each earned by the first two-sided mic run (mic-20260914-220345).

1. Transcription language pinned to English.
   Two of thirty transcripts in scenario A came back as Chinese characters
   while the AC was running, and ARGO answered one of them. Input
   transcription with no language hint hallucinates CJK on noise - a known
   failure of Whisper-family transcribers. Pin the language.

2. Three instruction lines, each against a measured behaviour:
   - 6 of 25 replies opened with "Let me lay out..." / "Okay, let me think
     about..." - preamble before substance.
   - "OK, now, let me think for a second here" got a reply. He was keeping
     the floor, not yielding it.
   - Two replies ran 49 s and 35 s spoken. An open question earns a real
     answer, but a spoken monologue that long is a lecture.

3. The harness flags a scenario shorter than 20 s with no events and offers a
   redo. C, D and F were 12 s, 3 s and 5 s with 0 events - Enter pressed twice.
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

# --- 1. transcription language ----------------------------------------------------
patch("livekit_realtime_agent.py",
'''    reduction = (cfg.input_noise_reduction or "").strip().lower()''',
'''    # Pin the input transcription language. Without it, two of thirty turns in
    # the first real mic run came back as Chinese characters (the AC was on)
    # and ARGO answered one. Typed object first, dict fallback, logged either
    # way - same pattern as turn detection.
    try:
        from openai.types import realtime as _rt

        transcription = _rt.AudioTranscription(model="gpt-4o-mini-transcribe", language="en")
        logger.info("[Audio] input transcription: gpt-4o-mini-transcribe language=en (typed)")
    except Exception:
        transcription = {"model": "gpt-4o-mini-transcribe", "language": "en"}
        logger.info("[Audio] input transcription: gpt-4o-mini-transcribe language=en (dict)")
    kwargs["input_audio_transcription"] = transcription

    reduction = (cfg.input_noise_reduction or "").strip().lower()''',
"agent: transcription language=en", marker='kwargs["input_audio_transcription"]')

patch("livekit_realtime_agent.py",
'''        for optional in ("turn_detection", "input_audio_noise_reduction"):''',
'''        for optional in ("turn_detection", "input_audio_noise_reduction", "input_audio_transcription"):''',
"agent: transcription in the fallback strip list", marker='"input_audio_noise_reduction", "input_audio_transcription")')

# --- 2. instructions ------------------------------------------------------------------
patch("core/livekit_config.py",
'''    "Do not repeat his question back, do not open with an acknowledgement, do "
    "not narrate what you are about to do, and do not explain your own "
    "architecture, tools or limits unless he asks about them. "''',
'''    "Do not repeat his question back, do not open with an acknowledgement, do "
    "not narrate what you are about to do, and do not explain your own "
    "architecture, tools or limits unless he asks about them. "
    "Lead with the answer itself - never with 'let me lay out', 'let me think "
    "about', 'okay, so' or any other run-up. The first words you say should "
    "already be the substance. "
    "If he says he is thinking, has another question coming, or is about to "
    "turn something on - 'let me think for a second', 'hold that thought', "
    "'one more thing' - he is keeping the floor. Say nothing. Wait. "
    "Keep a spoken answer under about twenty seconds unless he asked for the "
    "long version; give the headline and one reason, then offer the rest. A "
    "long monologue out loud is a lecture, whatever the question was. "''',
"instructions: lead with substance / hold the floor / no monologues",
marker="The first words you say should")

# --- 3. harness: catch an accidental double-Enter ----------------------------------------
patch("tools/voice_scenarios.py",
'''    input("  ...recording. Press Enter when this scenario is done.")

    audio = recorder.stop()''',
'''    input("  ...recording. Press Enter when this scenario is done.")

    # Scenarios C, D and F in the first real run were 12 s, 3 s and 5 s with
    # nothing heard - Enter pressed twice. Catch that here instead of writing
    # an empty file and calling it captured.
    from core import voice_events as _ve

    if time.time() - started < 20 and not _ve.read_since(offset):
        answer = input("  That was under 20 s and ARGO heard nothing. "
                       "Enter = keep recording this scenario, s = skip it: ").strip().lower()
        if answer != "s":
            input("  ...still recording. Press Enter when this scenario is done.")

    audio = recorder.stop()''',
"harness: short-scenario redo prompt", marker="Enter pressed twice")

print("\n".join(log))
import ast
for rel in ("livekit_realtime_agent.py", "core/livekit_config.py", "tools/voice_scenarios.py"):
    ast.parse(io.open(ROOT / rel, encoding="utf-8").read())
print("all three parse")
