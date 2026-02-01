# ARGO — Local Voice AI (VAD-Only)

**ARGO** is a fully local, always-listening voice assistant with a first‑class UI debugger. It runs entirely on your machine and streams live status + logs to the dashboard.

**Key points**
- **Wake word removed by design** — ARGO is VAD‑only (always listening).
- **UI debugger is required** — it is the primary visibility surface.
- **Local‑first** — no cloud dependencies for speech or TTS.
- **Deterministic system facts** — system health/specs never call the LLM.

**Web UI:** http://localhost:8000  
**WebSocket:** ws://localhost:8001/ws

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
Audio → VAD → STT → LLM → TTS
              ↘︎ WebSocket (live status + logs) → UI Debugger
```

- Audio frames are continuously monitored by **VAD**.
- Detected speech is transcribed with **Whisper** (STT).
- Prompts are sent to **Ollama** (LLM).
- Responses are synthesized with **Piper** (TTS).
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

### Run ARGO
```powershell
python main.py
```

### Open the UI Debugger
- http://localhost:8000

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

## Milestone: Music + System Health Hardening (Jan 2026)

**Why:** Reduce LLM dependency for system facts and make music control predictable under load.

Highlights:
- System health/hardware queries now return immediate, numeric answers
- Disk queries are deterministic and never fall back to the LLM
- Music playback preempts safely and resolves with stricter matching
- Local music index available for fast playback without Jellyfin
- OpenRGB lighting control supported via deterministic commands

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

## Quick Start Validation
A new user should be able to:
1) Clone repo
2) Install deps
3) Run `python main.py`
4) Open http://localhost:8000 and see live system state

If your setup does not match that flow, check the Issues section and logs in the UI.
