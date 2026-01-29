# Install

## Requirements
- **Windows 10/11**
- **Python 3.10+** (3.11 recommended)
- **Ollama** (local LLM runtime)
- **Piper** (local TTS)

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## LLM Runtime
```powershell
ollama serve
ollama pull qwen:latest
```

## Run
```powershell
python main.py
```

## Music Indexing Lifecycle
- SQLite DB is created by Jellyfin ingest.
- ARGO runs without it.
- Music commands are disabled until indexed.
- Re-ingest required if schema version changes.

## Milestone: Music + System Health Hardening (Jan 2026)

**Why:** keep system facts deterministic and music control stable.

System health and disk queries are deterministic and do not use the LLM.
