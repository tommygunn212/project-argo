# ARGO — Local Voice AI

**ARGO** is a local-first voice assistant with a first-class UI debugger, a smooth LiveKit/OpenAI Realtime conversation path, and a comprehensive control surface. It runs on your machine and streams live status + logs to the dashboard.

**Key points**
- **Smooth voice mode** — LiveKit WebRTC + OpenAI Realtime is the preferred fast back-and-forth conversation path.
- **Classic VAD fallback** — the local STT/LLM/TTS pipeline remains available for commands, diagnostics, and fallback speech.
- **Dual UI surfaces** — original debugger (`/`) and full-featured Frontend V2 (`/v2`).
- **Multi-engine STT** — OpenAI Cloud (`gpt-4o-mini-transcribe`), Azure, Faster Whisper, OpenAI Whisper — switchable at runtime.
- **Multi-engine TTS** — OpenAI TTS (`gpt-4o-mini-tts`, 13 voices), Edge TTS, Azure Neural — switchable at runtime.
- **Cortana portrait fallback** — `/v2` uses the local Cortana/Hedra portrait asset while realtime avatar providers are evaluated.
- **Speaker identity groundwork** — Speechmatics speaker-ID readiness is exposed in status for future "who is who" voice detection.
- **Phone/iPad ready status** — `/api/mobile-access` reports the same-network URL for testing ARGO from another device.
- **14 gate tuning sliders** — adjust VAD, barge-in, confidence, tokens, and verbosity in real time.
- **Deterministic system facts** — system health/specs never call the LLM.
- **Natural language flexibility** — supports colloquial phrasing for core commands.
- **Self-diagnostics** — ARGO can check its own health and propose fixes.
- **Security aware** — binds are configurable; local dev can serve the dashboard to the LAN for phone/iPad testing.
- **Memory backend choice** — SQLite by default, optional PostgreSQL backend for durable long-term memory experiments.

**Web UI (Classic):** http://localhost:8000
**Web UI (V2):** http://localhost:8000/v2
**WebSocket:** ws://localhost:8001/ws
**Mobile/iPad status:** http://localhost:8000/api/mobile-access

**Version:** see [core/version.py](core/version.py)

**Disclaimer:** See [ARGO_DISCLAIMER.md](ARGO_DISCLAIMER.md)

---

## Versioning

- This project uses Semantic Versioning.
- v1.0.0 is the initial public release.
- v1.5.0 marks architectural hardening and runtime stability.
- v2.0.0 is reserved for installer and onboarding.

---

## Architecture Overview

```
Smooth voice: Browser mic → LiveKit WebRTC → OpenAI Realtime → LiveKit audio
Classic path: Audio → VAD → STT → LLM → TTS
                         ↘︎ Memory backend (SQLite/PostgreSQL/Mem0)
                         ↘︎ WebSocket (live status + logs) → UI (v1 + v2)
```

- Audio frames are continuously monitored by **VAD**.
- Smooth voice mode lets one realtime session own listening, speaking, and interruption.
- Detected speech is transcribed by **STT** (OpenAI Cloud, Faster Whisper, or Azure).
- Prompts are sent to **GPT-4o-mini** (LLM) with streaming.
- Durable explicit memories are stored through `core.memory_store` using SQLite by default or PostgreSQL when configured.
- Responses are synthesized by **TTS** (OpenAI, Edge, or Azure Neural).
- The UI receives **live logs + status** over WebSocket.

---

## Install & Run

### Requirements
- **Python:** 3.10+ (3.11 recommended)
- **Ollama** running locally (LLM)
- **Piper** installed or callable via `python -m piper`
- **OpenRGB** (optional, for lighting control)

### Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Start Required Services
```powershell
ollama serve
```
Ensure the model is available:
```powershell
ollama pull qwen:latest
```

### Optional PostgreSQL Memory Backend
SQLite remains the default. To try PostgreSQL for durable memory:

```powershell
$env:ARGO_MEMORY_BACKEND="postgres"
$env:ARGO_POSTGRES_DSN="postgresql://argo:argo@localhost:5432/argo"
python scripts/migrate_memory_to_postgres.py --dsn $env:ARGO_POSTGRES_DSN
```

PostgreSQL is currently used for explicit memory records and the new conversation-turn storage table. If Postgres is not configured, ARGO stays on `data/memory.db`.

### Run ARGO
```powershell
.\scripts\start_livekit_realtime.ps1
python main.py
```

### Open the UI Debugger
- http://localhost:8000
- http://localhost:8000/v2

### Test From Phone Or iPad

Start ARGO, open `http://localhost:8000/api/mobile-access`, then use the reported `http_url` from a device on the same network. The browser must allow microphone access for **Start Smooth Voice**.

---

## Music Indexing (Local-First)

ARGO supports a local JSON music index for fast, deterministic playback.

- Index path: data/music_index.json
- Build it with: scripts/rebuild_music_index.py
- Enable local mode with: MUSIC_SOURCE=local

Jellyfin ingest is optional and no longer required for music commands.

---

## Audio Device Configuration

Set device indices in config.json:

```json
{
    "audio": {
        "input_device_index": 35,
        "output_device_index": 34
    }
}
```

---

## Lighting Control (OpenRGB)

Lighting commands target OpenRGB devices when these are set:

- OPENRGB_EXE=path\to\OpenRGB.exe
- OPENRGB_DEVICES=0,1

OpenRGB server must be running.

---

## System Health & Hardware (Deterministic)

These queries are **deterministic** and **never call the LLM**:
- CPU, memory, GPU, OS, motherboard identity
- Disk health and free space (including per-drive queries)

Examples:
- “How full is my D drive?”
- “Which drive has the most free space?”
- “What drive is the fullest?”

---
## Deterministic vs LLM Intent Routing (v1.6.1+)

ARGO distinguishes between **canonical commands** and **LLM-routed queries**:

### Canonical Commands (Always Deterministic)
- System health / hardware queries (CPU, memory, GPU, disk)
- Music playback commands
- Lighting control (OpenRGB)
- Stop / pause / resume commands

These commands **bypass STT confidence gates** entirely. Even if Whisper reports low confidence, canonical commands execute immediately without LLM fallback.

### LLM-Routed Queries
- General knowledge questions
- Conversational requests
- Ambiguous or unstructured input

If a query contains an **unresolved noun phrase** (e.g., "tell me about it" with no prior context), ARGO responds with a clarification prompt instead of LLM speculation.

### Confidence Gating Behavior
- Canonical/deterministic commands: **No confidence gate** — always execute
- LLM queries: Subject to STT confidence thresholds
- Unresolved references: Clarification prompt, no LLM call

---
## Milestone: Music + System Health Hardening (Jan 2026)

**Why:** Reduce LLM dependency for system facts and make music control predictable under load.

Highlights:
- System health/hardware queries now return immediate, numeric answers
- Disk queries are deterministic and never fall back to the LLM
- Music playback preempts safely and resolves with stricter matching
- Local music index available for fast playback without Jellyfin
- OpenRGB lighting control supported via deterministic commands

---

## Milestone: Self-Diagnostics + Security Hardening (Mar 2026)

**Why:** ARGO should know when its own subsystems are failing and be able to help fix them — and do it securely.

Highlights:
- Self-diagnostics module checks Ollama, Piper, Whisper, and audio health
- Assisted recovery proposes fixes and executes only with user approval
- Frontend diagnostics panel with recovery prompts
- All servers bound to localhost (no network exposure)
- Secrets moved to environment variables
- Requirements pinned for reproducible builds

---

## Milestone: Frontend V2, Engine Upgrades & Barge-In Overhaul (Mar 2026)

**Why:** Give ARGO a production-quality control surface with runtime engine switching and reliable interrupt handling.

Highlights:
- Frontend V2 at `/v2` — 6-tab cyberpunk UI with full WebSocket integration
- 14 gate tuning sliders for real-time audio/STT/response adjustment
- STT/TTS engine switching: choose engine, model, and voice at runtime
- STT upgraded to `gpt-4o-mini-transcribe`, TTS to `gpt-4o-mini-tts`
- 13 OpenAI TTS voices (including verse, marin, cedar)
- Barge-in overhaul: multi-engine stop, suppression guards, buffer clearing
- Response quality: max_tokens 1024, max_sentences 10, rewritten system prompt

---

## Milestone: PostgreSQL Memory Backend (May 2026)

**Why:** Keep SQLite as the reliable local default while making ARGO ready for stronger long-term memory, semantic recall, and future pgvector work.

Highlights:
- `core.memory_store` now resolves SQLite or PostgreSQL from config/environment
- PostgreSQL schema mirrors the durable memory API without changing existing callers
- Completed LLM conversation turns are stored for long-term recall experiments
- Matching durable turns are included in future memory context when relevant
- Migration script copies existing `data/memory.db` records into Postgres
- Version normalized to v1.8.0 for the memory backend milestone

---

## Issues & Fixes

### 1) Piper not found
**Symptom:** Logs show `Piper not in PATH` or no TTS output.  
**Fix:** Install Piper and ensure it’s callable (`python -m piper` works). The UI will surface this in the Solutions panel.

### 2) No audio output
**Symptom:** TTS logs appear but nothing plays.  
**Fix:** Verify your output device index and that the device is not muted. Check device list in logs and set output index accordingly.

### 3) Over‑sensitive VAD
**Symptom:** Frequent false triggers or constant interruptions.  
**Fix:** Increase VAD threshold in `main.py` to reduce sensitivity.

### 4) Whisper hallucinations / empty transcriptions
**Symptom:** STT returns empty or nonsense for quiet audio.  
**Fix:** Speak closer to the microphone or raise input gain. Ensure audio normalization is enabled in `main.py`.

---

## What Changed
- Wake word detection removed
- Always‑listening VAD pipeline
- UI debugger + WebSocket observability as core runtime components
- Deterministic system health/specs and local music indexing

---

## Testing

Run the test suite with:
```bash
pytest
```

**Current status (v1.6.1):** 451 tests passing, 12 pre-existing failures (test debt), 5 skipped.

Known test failures are tracked in [TEST_DEBT.md](TEST_DEBT.md). These are non-blocking and do not affect runtime behavior.

---

## Quick Start Validation
A new user should be able to:
1) Clone repo
2) Install deps
3) Run `python main.py`
4) Open http://localhost:8000 and see live system state

If your setup does not match that flow, check the Issues section and logs in the UI.
