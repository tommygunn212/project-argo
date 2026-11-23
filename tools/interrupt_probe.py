"""Spoken test: does one sharp "Stop." cut ARGO off mid-answer?

    .venv\\Scripts\\python tools\\interrupt_probe.py

Wakes her, asks for a long answer, waits until she has been talking for a
couple of seconds, says "Stop.", then measures from her real audio track how
long she kept talking after the word began. Also reports whether the urgent
phrase gate fired or LiveKit's normal interruption did the work.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import wake_probe as wp  # noqa: E402

ROOM = "argo-interrupt-probe"
STOPPED_WITHIN = 1.5  # seconds after "Stop." starts


class TimedEars(wp.Ears):
    def __init__(self) -> None:
        super().__init__()
        self.last_loud = 0.0
        self.loud_times: list[float] = []

    async def listen(self, track) -> None:
        from livekit import rtc

        async for ev in rtc.AudioStream(track):
            f = ev.frame
            data = np.frombuffer(f.data, dtype=np.int16).astype(np.float32)
            if data.size == 0:
                continue
            self.frame_seconds = f.samples_per_channel / f.sample_rate
            if float(np.sqrt(np.mean(data * data))) > wp.LOUD_RMS:
                self.loud_frames += 1
                self.last_loud = time.time()
                self.loud_times.append(self.last_loud)


async def probe() -> int:
    from livekit import api, rtc

    from core import voice_events
    from core.livekit_config import ensure_livekit_agent_dispatch, get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    wake = (cfg.wake_phrases or ("hey argo",))[0]
    lines = {
        "ask": f"{wake.capitalize()}, tell me the whole history of the London Underground, "
               "in detail, from the very beginning.",
        "stop": "Stop.",
    }
    print("synthesizing test speech...")
    pcm = {k: await asyncio.to_thread(wp.synthesize, v) for k, v in lines.items()}

    lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
    room = rtc.Room()
    ears = TimedEars()
    tasks: list[asyncio.Task] = []
    ok = False
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=ROOM, empty_timeout=120))
        offset = voice_events.tail_position()
        await asyncio.to_thread(ensure_livekit_agent_dispatch, room_name=ROOM, config=cfg)

        @room.on("track_subscribed")
        def _on_track(track, _pub, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                tasks.append(asyncio.ensure_future(ears.listen(track)))

        token = (api.AccessToken(cfg.api_key, cfg.api_secret)
                 .with_identity("interrupt-probe")
                 .with_grants(api.VideoGrants(room_join=True, room=ROOM)).to_jwt())
        await room.connect(cfg.url, token)
        source = rtc.AudioSource(wp.RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        mic = wp.Mic(source)
        tasks.append(asyncio.ensure_future(mic.run()))

        started = time.time()
        while time.time() - started < 30:
            if any(e.get("kind") == "session_start" and e.get("room") == ROOM
                   for e in voice_events.read_since(offset)):
                break
            await asyncio.sleep(0.3)
        else:
            print("FAIL - ARGO never started a session")
            return 1
        await asyncio.sleep(4)

        print(f"> saying: {lines['ask']!r}")
        await mic.say(pcm["ask"])
        waited = time.time()
        while ears.loud_seconds() < 2.5 and time.time() - waited < 20:
            await asyncio.sleep(0.1)
        if ears.loud_seconds() < 2.5:
            print("FAIL - she never started a long answer")
            return 1
        print(f"  she has talked {ears.loud_seconds()}s; saying 'Stop.'")
        mark = voice_events.tail_position()
        wp.ROOM = ROOM
        act_mark = wp.actions_offset()
        stop_at = time.time()
        await mic.say(pcm["stop"])
        await asyncio.sleep(5)
        # Where her audio first goes quiet for 0.3 s after "Stop." began.
        after = [t for t in ears.loud_times if t >= stop_at]
        cut_at = stop_at
        for a, b in zip([stop_at] + after, after + [float("inf")]):
            if b - a > 0.3:
                cut_at = a
                break
        cut = round(cut_at - stop_at, 2)
        talked_again = round(sum(1 for t in after if t > cut_at + 0.3) * ears.frame_seconds, 2)
        kinds = [e.get("kind") for e in voice_events.read_since(mark)]
        heard = [e.get("text") for e in voice_events.read_since(mark)
                 if e.get("kind") == "heard" and str(e.get("final")) == "True"]
        urgent = "urgent_interrupt" in kinds
        tools = wp.tools_run_since(act_mark)
        ok = cut <= STOPPED_WITHIN and talked_again < wp.SPOKE_SECONDS and not tools
        print(f"  {'PASS' if ok else 'FAIL'}: went quiet {cut}s after 'Stop.' began "
              f"(limit {STOPPED_WITHIN}s); talked again {talked_again}s (want 0); "
              f"tools={tools}; hush={'urgent_hush' in kinds}; urgent={urgent}; heard={heard}")
    finally:
        for t in tasks:
            t.cancel()
        try:
            await room.disconnect()
        except Exception:
            pass
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ROOM))
        except Exception:
            pass
        await lk.aclose()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
