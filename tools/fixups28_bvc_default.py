"""Stop defaulting LiveKit BVC on against a self-hosted server.

Background voice cancellation is a LiveKit Cloud filter. This deployment runs
ws://127.0.0.1:7880. tests/test_realtime_audio.py has asserted since it was
written that BVC must be off by default, with the reason in its docstring: it
was on for one afternoon and was a credible suspect when Smooth Voice connected
and then heard nothing. The code default said True anyway, so the invariant was
documented and violated at the same time.

This does not touch OpenAI's server-side input_audio_noise_reduction, which is
a different mechanism, is confirmed accepted by the model, and stays on.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PY = ROOT / "core" / "livekit_config.py"
CONFIG_JSON = ROOT / "config.json"

EDITS = [
    (
        "dataclass default",
        "    noise_cancellation: bool = True\n",
        "    # LiveKit Cloud only. Off unless this actually runs against Cloud.\n"
        "    noise_cancellation: bool = False\n",
    ),
    (
        "resolved default",
        '                cfg, "ARGO_REALTIME_NOISE_CANCELLATION", "livekit.noise_cancellation", True\n',
        '                cfg, "ARGO_REALTIME_NOISE_CANCELLATION", "livekit.noise_cancellation", False\n',
    ),
]


def main() -> int:
    text = CONFIG_PY.read_text(encoding="utf-8")
    for marker, old, new in EDITS:
        if old not in text:
            if new in text:
                print(f"  = {marker} (already applied)")
                continue
            print(f"  FAIL {marker}: anchor not found")
            return 1
        text = text.replace(old, new, 1)
        print(f"  + {marker}")
    CONFIG_PY.write_text(text, encoding="utf-8")

    # config.json is gitignored, so it is the live machine's own state.
    if CONFIG_JSON.is_file():
        data = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        livekit = data.get("livekit")
        if isinstance(livekit, dict) and livekit.get("noise_cancellation") is not False:
            livekit["noise_cancellation"] = False
            CONFIG_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print("  + config.json livekit.noise_cancellation -> false")
        else:
            print("  = config.json already false or key absent")

    # Read back from disk rather than trusting the write.
    check = CONFIG_PY.read_text(encoding="utf-8")
    print()
    print("  read-back audit:")
    resolved_probe = 'livekit.noise_cancellation", False'
    ok_dataclass = "OK " if "noise_cancellation: bool = False" in check else "MISSING"
    ok_resolved = "OK " if resolved_probe in check else "MISSING"
    print(f"    {ok_dataclass} dataclass default is False")
    print(f"    {ok_resolved} resolved default is False")

    sys.path.insert(0, str(ROOT))
    for module in [m for m in list(sys.modules) if m.startswith("core.")]:
        del sys.modules[module]
    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    print(f"    live noise_cancellation   : {cfg.noise_cancellation}")
    print(f"    live input_noise_reduction: {cfg.input_noise_reduction}  (unchanged, OpenAI side)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
