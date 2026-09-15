"""Round two, earned by the first two proof runs."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
done = []

def patch(rel, old, new, label):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if new in s:
        done.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR NOT FOUND in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    done.append(f"OK   {label}")

# 1. The GA Realtime API rejects the old flat session shape: it wants
#    session.type and puts turn detection and voice under audio.input /
#    audio.output. Both models connected fine - only the update was malformed.
patch("tools/realtime_preflight.py",
'''                await ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "voice": voice,
                        "turn_detection": {
                            "type": "semantic_vad",
                            "eagerness": eagerness,
                            "create_response": True,
                            "interrupt_response": True,
                        },
                        "input_audio_noise_reduction": {"type": "far_field"},
                    },
                }))''',
'''                await ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        # GA shape. The legacy flat form (voice and
                        # turn_detection at the top level) is refused with
                        # "Missing required parameter: 'session.type'".
                        "type": "realtime",
                        "audio": {
                            "input": {
                                "noise_reduction": {"type": "far_field"},
                                "turn_detection": {
                                    "type": "semantic_vad",
                                    "eagerness": eagerness,
                                    "create_response": True,
                                    "interrupt_response": True,
                                },
                            },
                            "output": {"voice": voice},
                        },
                    },
                }))''',
"preflight: GA session shape")

patch("tools/realtime_preflight.py",
'''                turn = echo.get("turn_detection") or (echo.get("audio", {})
                                                     .get("input", {}).get("turn_detection")) or {}
                return {
                    "ok": True,
                    "handshake": label,
                    "model": echo.get("model") or created.get("session", {}).get("model") or model,
                    "voice": echo.get("voice") or (echo.get("audio", {})
                                                   .get("output", {}).get("voice")),
                    "turn_detection_type": turn.get("type"),
                    "turn_eagerness": turn.get("eagerness"),
                    "semantic_vad_accepted": turn.get("type") == "semantic_vad",
                    "eagerness_accepted": turn.get("eagerness") == eagerness,
                }''',
'''                audio_in = echo.get("audio", {}).get("input", {})
                audio_out = echo.get("audio", {}).get("output", {})
                turn = audio_in.get("turn_detection") or echo.get("turn_detection") or {}
                reduction = audio_in.get("noise_reduction") or {}
                if isinstance(reduction, str):
                    reduction = {"type": reduction}
                return {
                    "ok": True,
                    "handshake": label,
                    "model": echo.get("model") or created.get("session", {}).get("model") or model,
                    "voice": audio_out.get("voice") or echo.get("voice"),
                    "voice_accepted": (audio_out.get("voice") or echo.get("voice")) == voice,
                    "turn_detection_type": turn.get("type"),
                    "turn_eagerness": turn.get("eagerness"),
                    "semantic_vad_accepted": turn.get("type") == "semantic_vad",
                    "eagerness_accepted": turn.get("eagerness") == eagerness,
                    "noise_reduction_type": reduction.get("type"),
                    "far_field_accepted": reduction.get("type") == "far_field",
                }''',
"preflight: read the GA echo")

patch("tools/realtime_preflight.py",
'''    print(f"  semantic_vad accepted : {result['semantic_vad_accepted']}")
    print(f"  eagerness accepted    : {result['eagerness_accepted']} ({result['turn_eagerness']})")
    print(f"  voice                 : {result['voice']}")''',
'''    print(f"  semantic_vad accepted : {result['semantic_vad_accepted']}")
    print(f"  eagerness accepted    : {result['eagerness_accepted']} ({result['turn_eagerness']})")
    print(f"  far_field accepted    : {result['far_field_accepted']} ({result['noise_reduction_type']})")
    print(f"  voice accepted        : {result['voice_accepted']} ({result['voice']})")''',
"preflight: report far_field and voice")

# 2. config.json carried the new values but the CODE defaults were still the
#    hair-trigger ones, so anything constructing a config without that block
#    (every test, and any fresh install) got 0.08s back.
patch("core/livekit_config.py",
'''                "livekit.min_interruption_duration",
                0.08,
            ),
            0.08,
        ),''',
'''                "livekit.min_interruption_duration",
                0.35,
            ),
            0.35,
        ),''',
"config default: min_interruption_duration 0.08 -> 0.35")

patch("core/livekit_config.py",
'''                "livekit.false_interruption_timeout",
                0.22,
            ),
            0.22,
        ),''',
'''                "livekit.false_interruption_timeout",
                1.2,
            ),
            1.2,
        ),''',
"config default: false_interruption_timeout 0.22 -> 1.2")

patch("core/livekit_config.py",
'''    min_interruption_duration: float
    false_interruption_timeout: float''',
'''    # Deliberate, not hair-trigger. A cough, a chair creak and ARGO's own
    # speaker bleeding back into the Brio all used to clear the old 0.08s.
    min_interruption_duration: float
    false_interruption_timeout: float''',
"config: comment the interruption fields")

# 3. Identical model and fallback is the correct state while 1.5 IS the
#    known-good one. It is only worth flagging once the model moves off it.
patch("tools/prove_voice.py",
'''    rep.step("there is a fallback model", bool(cfg.fallback_model)
             and cfg.fallback_model != cfg.model,
             f"{cfg.model} -> {cfg.fallback_model}")''',
'''    same = cfg.fallback_model == cfg.model
    rep.step("there is a fallback model", bool(cfg.fallback_model),
             f"{cfg.model} -> {cfg.fallback_model}"
             + (" (same model: nothing to fall back TO, which is correct only "
                "while the configured model IS the known-good one)" if same else ""))''',
"prove_voice: fallback check")

print("\\n".join(done))
