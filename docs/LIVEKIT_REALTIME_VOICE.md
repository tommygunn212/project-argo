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

## Run

```powershell
.\scripts\start_livekit_realtime.ps1
.\.venv\Scripts\python.exe main.py
```

Open `http://localhost:8000/v2`, go to Voice, then start Realtime.

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
- Agent name: `argo-realtime`, dispatched through the browser room token

Use environment variables for production secrets:

- `OPENAI_API_KEY`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

The checked-in local LiveKit server uses the dev key in
`livekit-server/livekit.yaml`.

## Why This Replaces The Old Conversation Loop

The old path had separate STT, LLM, TTS, and local playback queues. It could
detect barge-in, but a stale TTS request or audio lock could still delay the
next user turn.

The realtime path avoids that split. The same session owns listening, speaking,
and interruption, so user speech can cancel assistant speech without waiting for
an old synthesis/playback queue to unwind.
