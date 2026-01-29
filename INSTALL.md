# Install

## Requirements
- **Windows 10/11**
- **Python 3.10+** (3.11 recommended)
- **Ollama** (local LLM runtime)
- **Piper** (local TTS)
- **OpenRGB** (optional, for lighting control)

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

## Music Indexing (Local-First)

ARGO supports a local JSON music index for fast, deterministic playback.

- Index path: data/music_index.json
- Build it with: scripts/rebuild_music_index.py
- Enable local mode with: MUSIC_SOURCE=local

Jellyfin ingest is optional and no longer required for music commands.

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

## Lighting Control (Optional)

Lighting commands target OpenRGB devices when these are set:

- OPENRGB_EXE=path\to\OpenRGB.exe
- OPENRGB_DEVICES=0,1

OpenRGB server must be running.

## Milestone: Music + System Health Hardening (Jan 2026)

**Why:** keep system facts deterministic and music control stable.

System health and disk queries are deterministic and do not use the LLM.
