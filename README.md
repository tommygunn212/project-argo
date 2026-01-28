# ARGO — Local Voice AI (VAD-Only)

**ARGO** is a fully local, always-listening voice assistant with a first‑class UI debugger. It runs entirely on your machine and streams live status + logs to the dashboard.

**Key points**
- **Wake word removed by design** — ARGO is VAD‑only (always listening).
- **UI debugger is required** — it is the primary visibility surface.
- **Local‑first** — no cloud dependencies for speech or TTS.

**Web UI:** http://localhost:8000  
**WebSocket:** ws://localhost:8001/ws

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
ollama pull qwen2:latest
```

### Run ARGO
```powershell
python main.py
```

### Open the UI Debugger
- http://localhost:8000

---

## Music Indexing Lifecycle

- SQLite DB is created by Jellyfin ingest.
- ARGO runs without it.
- Music commands are disabled until indexed.
- Re-ingest required if schema version changes.

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

---

## Quick Start Validation
A new user should be able to:
1) Clone repo
2) Install deps
3) Run `python main.py`
4) Open http://localhost:8000 and see live system state

If your setup does not match that flow, check the Issues section and logs in the UI.
