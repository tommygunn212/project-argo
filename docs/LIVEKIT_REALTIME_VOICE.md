# ARGO LiveKit Realtime Voice

Milestone: `1.9.0-livekit-realtime-voice`

This is the preferred voice-conversation path for ARGO when Tommy wants fast
back-and-forth conversation with natural interruption.

## Shape

- Browser mic/audio runs through LiveKit WebRTC.
- `livekit_realtime_agent.py` joins the room as the ARGO agent.
- OpenAI Realtime handles audio input, turn detection, speech output, and
  interruption inside one realtime session.
- The classic ARGO STT/LLM/TTS pipeline remains available as fallback and for
  command/control work.
- The local Cortana portrait is the UI fallback visual while a current realtime
  avatar provider is selected.
- Speechmatics speaker-ID readiness is exposed, but it is not forced into the
  OpenAI Realtime session.

## Run

```powershell
.\scripts\start_livekit_realtime.ps1
.\.venv\Scripts\python.exe main.py
```

Open `http://localhost:8000/v2`, then press **Start Smooth Voice**.

For iPad/phone testing on the same network, open:

```text
http://localhost:8000/api/mobile-access
```

Use the returned `http_url` from the mobile browser and allow microphone access.

To stop the realtime sidecar:

```powershell
.\scripts\stop_livekit_realtime.ps1
```

## Config

Realtime config lives under `livekit` in `config.json`.

Important defaults:

- URL: `ws://127.0.0.1:7880`
- Room: `argo-live`
- Model: `gpt-realtime`
- Voice: `marin`
- Minimum interruption duration: `0.08s`
- False-interruption timeout: `0.22s`
- Agent name: `argo-realtime`, dispatched through the browser room token
- Speaker identity provider: `speechmatics` (off by default)

Use environment variables for production secrets:

- `OPENAI_API_KEY`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `SPEECHMATICS_API_KEY` (only needed when speaker identity experiments are enabled)

The checked-in local LiveKit server uses the dev key in
`livekit-server/livekit.yaml`.

## Why This Replaces The Old Conversation Loop

The old path had separate STT, LLM, TTS, and local playback queues. It could
detect barge-in, but a stale TTS request or audio lock could still delay the
next user turn.

The realtime path avoids that split. The same session owns listening, speaking,
and interruption, so user speech can cancel assistant speech without waiting for
an old synthesis/playback queue to unwind.

## Cortana Companion Notes

The Cortana-style repo that inspired this pass uses a LiveKit agent pipeline
with Speechmatics diarization, Silero VAD, a turn detector, and an old Hedra
Realtime avatar. ARGO keeps the useful parts as separate, inspectable pieces:

- Smooth conversation remains OpenAI Realtime because it already fixed the
  barge-in feel.
- Speaker identity is prepared through Speechmatics readiness/status and will
  become a sidecar or alternate pipeline when enabled.
- The Cortana portrait is local and stable in `/v2`.
- Legacy Hedra Realtime is disabled by default because that provider path is no
  longer available.
