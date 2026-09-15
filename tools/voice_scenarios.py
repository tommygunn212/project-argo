"""The six microphone scenarios, with a gate so they cannot run into a void.

    .venv\\Scripts\\python tools\\voice_scenarios.py
    .venv\\Scripts\\python tools\\voice_scenarios.py --only c e

The first version of this recorded ten minutes of Tommy talking and captured
nothing: the browser was not connected, so no agent was in the room, and
there was no check that would notice. It also guessed at pyaudio (not
installed here) and scraped whichever log looked freshest for a line format
the realtime worker does not use.

All three are fixed by being less clever. Before every scenario it asks
LiveKit whether an agent is actually in the room with you, and refuses to
start if not. Audio goes through sounddevice. Events come from
runtime/voice_tests/live_events.jsonl, which the session itself writes.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_ROOT = ROOT / "runtime" / "voice_tests"
AGENT_KIND = 4

SCENARIOS = {
    "a": ("Ten-turn brainstorm",
          "Have a real back-and-forth - something you're actually chewing on - and go\n"
          "  about ten turns. Watch for: does it hold the thread, does it repeat your\n"
          "  question back, does it feel like a collaborator or a command parser."),
    "b": ("One long multi-sentence question",
          "Ask something that takes four or five sentences, with real pauses in the\n"
          "  middle. It must NOT answer until you have finished."),
    "c": ("Interrupt her mid-answer",
          "Ask something that earns a long answer, then talk over her halfway. She\n"
          "  should stop fast, hear all of it, and answer the NEW thought.\n"
          "  Then try a single sharp \"stop\" - that should cut in immediately."),
    "d": ("Background noise",
          "Turn the AC or a fan on. Sit quiet for 20 seconds - she must not react -\n"
          "  then ask a normal question and check she still hears it."),
    "e": ("Deep request, interrupted mid-flight",
          "Ask for something that needs real work (\"plan out how I'd...\"), then start\n"
          "  talking again while she is thinking. The deep request must be cancelled\n"
          "  and she must answer the new thing, not read out the old answer."),
    "f": ("No double-speaking",
          "Ask two or three ordinary questions. Exactly one voice answers each time -\n"
          "  no echo, no second answer arriving late from the classic pipeline."),
}


# --- the gate -------------------------------------------------------------

def room_state() -> dict:
    """Who is actually in the room right now, per LiveKit."""
    import asyncio

    from livekit import api

    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()

    async def look():
        lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
        try:
            rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            for room in rooms:
                parts = (await lk.room.list_participants(
                    api.ListParticipantsRequest(room=room.name))).participants
                humans = [p.identity for p in parts if p.kind != AGENT_KIND]
                agents = [p.identity for p in parts if p.kind == AGENT_KIND]
                if humans or agents:
                    return {"room": room.name, "humans": humans, "agents": agents}
            return {"room": None, "humans": [], "agents": []}
        finally:
            await lk.aclose()

    try:
        return asyncio.run(look())
    except Exception as exc:
        return {"room": None, "humans": [], "agents": [], "error": f"{type(exc).__name__}: {exc}"}


def require_live_session() -> dict:
    """Refuse to record unless there is something on the other end.

    This is the check whose absence wasted a whole test run.
    """
    state = room_state()
    if state.get("error"):
        print(f"\n  Cannot reach LiveKit: {state['error']}")
        print("  Is livekit-server running?")
        return {}
    if not state["room"]:
        print("\n  NOT CONNECTED - no room exists.")
        print("  Open the ARGO dashboard and click 'Start Smooth Voice', then re-run.")
        return {}
    if not state["humans"]:
        print(f"\n  Room {state['room']!r} exists but your browser is not in it.")
        print("  Click 'Start Smooth Voice' in the dashboard, then re-run.")
        return {}
    if not state["agents"]:
        print(f"\n  Room {state['room']!r} has you but NO AGENT - nothing is listening.")
        print("  Anything you say now would be recorded into a void. Reconnect Smooth")
        print("  Voice; if an agent still does not join, run tools\\dispatch_probe.py.")
        return {}
    print(f"  live: room {state['room']!r}, you={state['humans'][0]}, agent={state['agents'][0]}")
    return state


# --- recording ------------------------------------------------------------

class MicRecorder:
    """Record the mic alongside the live session, via sounddevice.

    Windows shared-mode capture lets a second reader open the same microphone
    the browser is publishing, so this does not steal the mic from ARGO.
    """

    def __init__(self, path: Path, device: int | None, rate: int = 16000) -> None:
        self.path, self.device, self.rate = path, device, rate
        self._frames: list = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""
        self.peak = 0.0

    def _loop(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:
            self.error = f"sounddevice/numpy unavailable: {exc}"
            return
        try:
            with sd.InputStream(samplerate=self.rate, channels=1, dtype="int16",
                                device=self.device, blocksize=1024) as stream:
                while not self._stop.is_set():
                    block, overflowed = stream.read(1024)
                    if overflowed:
                        continue
                    self._frames.append(block.copy())
                    peak = float(np.abs(block).max()) / 32768.0
                    self.peak = max(self.peak, peak)
        except Exception as exc:
            self.error = f"could not record: {type(exc).__name__}: {exc}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if not self._frames:
            return {"recorded": False, "error": self.error or "no audio captured"}
        try:
            import numpy as np

            data = np.concatenate(self._frames, axis=0)
            with wave.open(str(self.path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(self.rate)
                out.writeframes(data.tobytes())
            return {"recorded": True, "file": self.path.name,
                    "seconds": round(len(data) / self.rate, 1),
                    "peak_level": round(self.peak, 4), "error": self.error}
        except Exception as exc:
            return {"recorded": False, "error": f"could not write wav: {exc}"}


# --- what the session reported -------------------------------------------

def summarise(events: list[dict]) -> dict:
    def of(kind):
        return [e for e in events if e.get("kind") == kind]

    heard = [e.get("text", "") for e in of("heard") if e.get("final")]
    said = [e for e in of("said") if str(e.get("role")) == "assistant"]

    # Time from the user going quiet to ARGO starting to speak.
    gaps, waiting_since = [], None
    for e in events:
        if e.get("kind") == "user_state" and e.get("new") == "listening":
            waiting_since = e["t"]
        if e.get("kind") == "agent_state" and e.get("new") == "speaking" and waiting_since:
            gaps.append(round(e["t"] - waiting_since, 2))
            waiting_since = None

    return {
        "transcripts": heard,
        "turns_heard": len(heard),
        "argo_replies": len(said),
        "reply_texts": [(e.get("text") or "")[:220] for e in said],
        "urgent_interrupts": len(of("urgent_interrupt")),
        "deep_think_calls": len(of("deep_think_start")),
        "deep_think_cancelled": len(of("deep_think_cancelled")),
        "errors": [e.get("detail") for e in of("error")],
        "response_gaps_seconds": gaps,
        "slowest_response_seconds": max(gaps) if gaps else None,
        "fastest_response_seconds": min(gaps) if gaps else None,
    }


def run_scenario(key: str, directory: Path, device: int | None) -> dict | None:
    from core import voice_events

    title, instruction = SCENARIOS[key]
    print("\n" + "=" * 72)
    print(f"  SCENARIO {key.upper()}  -  {title}")
    print("=" * 72)
    print(f"  {instruction}\n")

    state = require_live_session()
    if not state:
        print("\n  Skipping - fix the connection above and re-run this scenario.")
        return None

    input("\n  Press Enter to start, then talk...")
    offset = voice_events.tail_position()
    recorder = MicRecorder(directory / f"{key}.wav", device)
    recorder.start()
    started = time.time()

    input("  ...recording. Press Enter when this scenario is done.")

    # Scenarios C, D and F in the first real run were 12 s, 3 s and 5 s with
    # nothing heard - Enter pressed twice. Catch that here instead of writing
    # an empty file and calling it captured.
    from core import voice_events as _ve

    if time.time() - started < 20 and not _ve.read_since(offset):
        answer = input("  That was under 20 s and ARGO heard nothing. "
                       "Enter = keep recording this scenario, s = skip it: ").strip().lower()
        if answer != "s":
            input("  ...still recording. Press Enter when this scenario is done.")

    audio = recorder.stop()
    time.sleep(1.5)                      # let the last events land
    events = voice_events.read_since(offset)
    (directory / f"{key}-events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8")

    result = {
        "scenario": key, "title": title,
        "duration_seconds": round(time.time() - started, 1),
        "audio": audio, "event_count": len(events),
        "room": state.get("room"), "agent": (state.get("agents") or [None])[0],
        **summarise(events),
    }

    print(f"\n  heard {result['turns_heard']} turn(s), ARGO replied {result['argo_replies']} time(s), "
          f"{result['urgent_interrupts']} urgent interrupt(s)")
    if result["slowest_response_seconds"] is not None:
        print(f"  reply delay after you stopped: "
              f"{result['fastest_response_seconds']}s - {result['slowest_response_seconds']}s")
    if result["errors"]:
        print(f"  {len(result['errors'])} session error(s)")
    if audio.get("error"):
        print(f"  NOTE: {audio['error']}")
    if not events:
        print("  WARNING: the session reported no events. Something is wrong - stop and check.")
    return result


def main() -> int:
    from core.config import get_config
    from core.livekit_config import get_livekit_realtime_config

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", choices=sorted(SCENARIOS), default=sorted(SCENARIOS))
    parser.add_argument("--device", type=int, default=None, help="input device index")
    args = parser.parse_args()

    device = args.device
    if device is None:
        try:
            device = int(get_config().get("audio.input_device_index", 1))
        except Exception:
            device = None

    cfg = get_livekit_realtime_config()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = OUT_ROOT / f"mic-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)

    print(f"ARGO microphone scenarios - {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  {cfg.model} / {cfg.voice} / personality {cfg.personality}")
    print(f"  turn detection {cfg.turn_detection} (eagerness {cfg.turn_eagerness}), "
          f"noise cancellation {cfg.noise_cancellation}/{cfg.input_noise_reduction}")
    print(f"  interrupt after {cfg.min_interruption_duration}s and "
          f"{cfg.min_interruption_words} word(s); urgent: {', '.join(cfg.urgent_interrupt_phrases[:5])}...")
    print(f"  recording input device {device}")
    print(f"  writing to {directory}\n")
    print("Checking the session is actually live before anything is recorded:")
    if not require_live_session():
        print("\nNothing to record against. Connect Smooth Voice and re-run.")
        return 1

    results = [r for r in (run_scenario(k, directory, device) for k in args.only) if r]
    (directory / "summary.json").write_text(json.dumps({
        "generated": datetime.now().isoformat(),
        "config": {
            "model": cfg.model, "voice": cfg.voice, "personality": cfg.personality,
            "turn_detection": cfg.turn_detection, "turn_eagerness": cfg.turn_eagerness,
            "noise_cancellation": cfg.noise_cancellation,
            "input_noise_reduction": cfg.input_noise_reduction,
            "min_interruption_duration": cfg.min_interruption_duration,
            "min_interruption_words": cfg.min_interruption_words,
            "urgent_interrupt_phrases": list(cfg.urgent_interrupt_phrases),
        },
        "scenarios": results,
    }, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"Done - {len(results)}/{len(args.only)} scenario(s) captured.")
    print(f"{directory}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
