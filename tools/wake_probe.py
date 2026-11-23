"""Spoken end-to-end test of the wake word / sleep word gate - no human needed.

    .venv\\Scripts\\python tools\\wake_probe.py

A fake participant joins a throwaway room, ARGO is dispatched into it, and
real synthesized speech is played as that participant's microphone. Each step
is judged on two things that cannot be faked by a config label:

* the gate's own events in runtime/voice_tests/live_events.jsonl, and
* ARGO's actual audio track - how many seconds of non-silent sound she sent.

Steps (the session must be configured to start asleep):
  1. ordinary question while asleep   -> she stays silent
  2. "Hey Argo, can you hear me?"     -> wake event, and she speaks
  3. "Go to sleep."                   -> sleep event
  4. ordinary question while asleep   -> she stays silent

Exit 0 only if every step passes. The room is deleted afterwards either way.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

ROOM = "argo-wake-probe"
RATE = 24000
FRAME = RATE // 100  # 10 ms
LOUD_RMS = 400       # int16 RMS that counts as "she is making sound"
SPOKE_SECONDS = 0.6  # this much loud audio = she answered
ACTIONS = ROOT / "runtime" / "logs" / "actions.jsonl"


def actions_offset() -> int:
    try:
        return ACTIONS.stat().st_size
    except Exception:
        return 0


def tools_run_since(offset: int) -> list[str]:
    import json

    try:
        with ACTIONS.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            raw = handle.read()
    except Exception:
        return []
    names = []
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("room") == ROOM:
            names.append(rec.get("tool"))
    return names


def synthesize(text: str) -> np.ndarray:
    from openai import OpenAI

    from core.runtime_guard import ensure_openai_key

    ensure_openai_key()
    resp = OpenAI().audio.speech.create(
        model="gpt-4o-mini-tts", voice="onyx", input=text, response_format="pcm")
    return np.frombuffer(resp.content, dtype=np.int16)


class Mic:
    """Feeds silence continuously; say() queues speech into the same stream."""

    def __init__(self, source) -> None:
        self.source = source
        self.queue: list[np.ndarray] = []
        self.done_speaking = asyncio.Event()
        self.done_speaking.set()

    async def run(self) -> None:
        from livekit import rtc

        silence = np.zeros(FRAME, dtype=np.int16)
        buf = np.zeros(0, dtype=np.int16)
        while True:
            if buf.size == 0 and self.queue:
                buf = self.queue.pop(0)
            if buf.size:
                chunk, buf = buf[:FRAME], buf[FRAME:]
                if chunk.size < FRAME:
                    chunk = np.concatenate([chunk, silence[: FRAME - chunk.size]])
                if buf.size == 0 and not self.queue:
                    self.done_speaking.set()
            else:
                chunk = silence
            frame = rtc.AudioFrame(chunk.tobytes(), RATE, 1, FRAME)
            await self.source.capture_frame(frame)

    async def say(self, pcm: np.ndarray) -> None:
        self.done_speaking.clear()
        self.queue.append(pcm)
        await self.done_speaking.wait()


class Ears:
    """Counts how much non-silent audio ARGO sends."""

    def __init__(self) -> None:
        self.loud_frames = 0
        self.frame_seconds = 0.01

    def loud_seconds(self) -> float:
        return round(self.loud_frames * self.frame_seconds, 2)

    async def listen(self, track) -> None:
        from livekit import rtc

        async for ev in rtc.AudioStream(track):
            f = ev.frame
            data = np.frombuffer(f.data, dtype=np.int16).astype(np.float32)
            if data.size == 0:
                continue
            self.frame_seconds = f.samples_per_channel / f.sample_rate
            if float(np.sqrt(np.mean(data * data))) > LOUD_RMS:
                self.loud_frames += 1


async def probe() -> int:
    from livekit import api, rtc

    from core import voice_events
    from core.livekit_config import ensure_livekit_agent_dispatch, get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    print(f"server : {cfg.url}   agent: {cfg.agent_name}   start asleep: "
          f"{getattr(cfg, 'wake_start_asleep', '?')}")
    wake = (cfg.wake_phrases or ("hey argo",))[0]
    sleep = (cfg.sleep_phrases or ("go to sleep",))[0]

    lines = {
        "q1": "What's the weather going to be like tomorrow?",
        "wake": f"{wake.capitalize()}, can you hear me?",
        "sleep": f"{sleep.capitalize()}.",
        "q2": "Can you tell me a joke?",
    }
    print("synthesizing test speech...")
    pcm = {k: await asyncio.to_thread(synthesize, v) for k, v in lines.items()}

    lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
    room = rtc.Room()
    ears = Ears()
    results: list[tuple[str, bool, str]] = []
    tasks: list[asyncio.Task] = []
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=ROOM, empty_timeout=120))
        offset = voice_events.tail_position()
        await asyncio.to_thread(ensure_livekit_agent_dispatch, room_name=ROOM, config=cfg)

        @room.on("track_subscribed")
        def _on_track(track, _pub, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                print(f"hearing ARGO's audio from {participant.identity}")
                tasks.append(asyncio.ensure_future(ears.listen(track)))

        token = (api.AccessToken(cfg.api_key, cfg.api_secret)
                 .with_identity("wake-probe").with_name("wake probe")
                 .with_grants(api.VideoGrants(room_join=True, room=ROOM)).to_jwt())
        await room.connect(cfg.url, token)
        source = rtc.AudioSource(RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        mic = Mic(source)
        tasks.append(asyncio.ensure_future(mic.run()))

        started = time.time()
        while time.time() - started < 30:
            if any(e.get("kind") == "session_start" and e.get("room") == ROOM
                   for e in voice_events.read_since(offset)):
                break
            await asyncio.sleep(0.3)
        else:
            print("FAIL - ARGO never started a session in the probe room")
            return 1
        print("session started; settling 4s")
        await asyncio.sleep(4)

        async def step(name: str, key: str, expect_speech: bool, expect_event: str | None,
                       listen_for: float) -> None:
            mark = voice_events.tail_position()
            act_mark = actions_offset()
            before = ears.loud_seconds()
            print(f"\n> saying: {lines[key]!r}")
            await mic.say(pcm[key])
            await asyncio.sleep(listen_for)
            spoke = round(ears.loud_seconds() - before, 2)
            kinds = [e.get("kind") for e in voice_events.read_since(mark)]
            heard = [e.get("text") for e in voice_events.read_since(mark)
                     if e.get("kind") == "heard" and str(e.get("final")) == "True"]
            ok_speech = (spoke >= SPOKE_SECONDS) == expect_speech
            ok_event = expect_event is None or expect_event in kinds
            tools = tools_run_since(act_mark)
            ok_tools = expect_speech or not tools  # asleep: nothing may run
            ok = ok_speech and ok_event and ok_tools
            detail = (f"heard={heard} argo_audio={spoke}s tools={tools} events="
                      f"{[k for k in kinds if 'wake' in str(k) or 'sleep' in str(k)]}")
            print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail}")
            results.append((name, ok, detail))

        await step("asleep: ordinary question ignored", "q1", False, None, 8)
        await step("wake word wakes her and she answers", "wake", True,
                   "wake_word_triggered", 12)
        await step("sleep word puts her to sleep", "sleep", False, "sleep_word_triggered", 8)
        await step("asleep again: question ignored", "q2", False, None, 8)
    finally:
        for t in tasks:
            t.cancel()
        try:
            await room.disconnect()
        except Exception:
            pass
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ROOM))
        except Exception as exc:
            print(f"could not delete {ROOM!r}: {type(exc).__name__}")
        await lk.aclose()

    passed = sum(ok for _, ok, _ in results)
    print("\n" + "-" * 62)
    print(f"{'PASS' if passed == len(results) == 4 else 'FAIL'} - {passed}/{len(results)} steps")
    return 0 if passed == len(results) == 4 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
