"""Prove a realtime model works before ARGO is pointed at it.

Tommy's rule for the gpt-realtime-2.1 upgrade was: confirm the installed
stack supports it and a real smoke test succeeds - not a config edit and a
hopeful label. So this opens an actual Realtime session against the model,
sends the exact session settings ARGO would send, and reports what the server
echoed back.

    .venv\\Scripts\\python tools\\realtime_preflight.py
    .venv\\Scripts\\python tools\\realtime_preflight.py --model gpt-realtime-2.1
    .venv\\Scripts\\python tools\\realtime_preflight.py --model gpt-realtime-2.1 --apply

--apply writes the model into config.json, and ONLY if the smoke test passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


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


_ensure_api_key()

ENDPOINT = "wss://api.openai.com/v1/realtime?model={model}"


def _installed_versions() -> dict[str, str]:
    from importlib import metadata

    out = {}
    for package in ("livekit-agents", "livekit-plugins-openai", "openai", "livekit"):
        try:
            out[package] = metadata.version(package)
        except Exception:
            out[package] = "not installed"
    return out


async def smoke_test(model: str, voice: str, eagerness: str, timeout: float = 25.0) -> dict:
    """Open a real session, configure it the way ARGO does, report the echo."""
    import websockets

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"ok": False, "stage": "credentials", "error": "OPENAI_API_KEY is not set"}

    url = ENDPOINT.format(model=model)
    attempts = [
        ("GA (no beta header)", {"Authorization": f"Bearer {api_key}"}),
        ("beta realtime=v1", {"Authorization": f"Bearer {api_key}", "OpenAI-Beta": "realtime=v1"}),
    ]

    last_error = ""
    for label, headers in attempts:
        try:
            async with websockets.connect(url, additional_headers=headers,
                                          open_timeout=timeout, close_timeout=5) as ws:
                created = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if created.get("type") == "error":
                    last_error = json.dumps(created.get("error", created))
                    continue

                await ws.send(json.dumps({
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
                }))

                echo, error = None, None
                deadline = asyncio.get_running_loop().time() + timeout
                while asyncio.get_running_loop().time() < deadline:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                    if event.get("type") == "session.updated":
                        echo = event.get("session", {})
                        break
                    if event.get("type") == "error":
                        error = event.get("error")
                        break

                if error:
                    return {"ok": False, "stage": "session.update", "handshake": label,
                            "error": json.dumps(error), "created": created.get("session", {})}
                if echo is None:
                    return {"ok": False, "stage": "session.update", "handshake": label,
                            "error": "no session.updated before timeout"}

                audio_in = echo.get("audio", {}).get("input", {})
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
                }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    return {"ok": False, "stage": "connect", "error": last_error}


def apply_model(model: str) -> str:
    path = ROOT / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    previous = data.get("livekit", {}).get("model")
    data.setdefault("livekit", {})["model"] = model
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"config.json livekit.model: {previous} -> {model}"


async def main() -> int:
    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=cfg.model)
    parser.add_argument("--voice", default=cfg.voice)
    parser.add_argument("--eagerness", default=cfg.turn_eagerness)
    parser.add_argument("--apply", action="store_true",
                        help="write the model into config.json if the test passes")
    args = parser.parse_args()

    print("installed versions:")
    for package, version in _installed_versions().items():
        print(f"  {package:<24} {version}")
    print(f"\nconfigured model : {cfg.model}")
    print(f"testing model    : {args.model}")
    print(f"voice / eagerness: {args.voice} / {args.eagerness}")
    print("-" * 62)

    result = await smoke_test(args.model, args.voice, args.eagerness)
    print(json.dumps(result, indent=2))
    print("-" * 62)

    if not result.get("ok"):
        print(f"FAIL - {args.model} did not complete a real session. Not applying.")
        return 1

    print(f"PASS - opened a live session on {result['model']}")
    print(f"  semantic_vad accepted : {result['semantic_vad_accepted']}")
    print(f"  eagerness accepted    : {result['eagerness_accepted']} ({result['turn_eagerness']})")
    print(f"  far_field accepted    : {result['far_field_accepted']} ({result['noise_reduction_type']})")
    print(f"  voice accepted        : {result['voice_accepted']} ({result['voice']})")

    if not result["semantic_vad_accepted"]:
        print("\nWARNING: the server did not echo semantic_vad. Turn-taking would fall "
              "back to the API default - fix that before switching models.")
        return 1

    if args.apply:
        print("\n" + apply_model(args.model))
        print("Restart the realtime worker for it to take effect.")
    else:
        print("\nRe-run with --apply to write this model into config.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
