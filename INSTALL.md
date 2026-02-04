# ARGO Installation Guide

## Quick Install (Recommended)

**One-liner for fresh Windows machines:**

```powershell
# Run in PowerShell as Administrator
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/tommygunn212/project-argo/audio-reset-phase0/install_argo.ps1 | iex"
```

This will:
- ✅ Check Python 3.10+ and Git
- ✅ Clone ARGO to `%LOCALAPPDATA%\ARGO`
- ✅ Create virtual environment
- ✅ Install all Python dependencies
- ✅ Download Piper TTS + Ryan voice
- ✅ Create desktop shortcut

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Windows** | 10/11 | x64 only |
| **Python** | 3.10+ | 3.11 recommended, [download](https://python.org) |
| **Git** | Any | [download](https://git-scm.com/download/win) |
| **Ollama** | Latest | For LLM, [download](https://ollama.ai) |

---

## Manual Install

If you prefer manual setup:

```powershell
# 1. Clone
git clone https://github.com/tommygunn212/project-argo.git argo
cd argo

# 2. Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
pip install tzdata  # Windows timezone support

# 4. Start Ollama (separate terminal)
ollama serve
ollama pull llama3.2

# 5. Run ARGO
python main.py
```

---

## Post-Install Setup

### 1. Configure Audio Devices

List devices:
```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Edit `config.json`:
```json
{
    "audio": {
        "input_device_index": 1,
        "output_device_index": 2
    }
}
```

### 2. API Keys (Optional)

| Key | Purpose | Where to get |
|-----|---------|--------------|
| `PORCUPINE_ACCESS_KEY` | Wake word detection | [picovoice.ai](https://picovoice.ai) |
| `OPENAI_API_KEY` | Cloud STT (optional) | [openai.com](https://openai.com) |

Set in environment or `config.json`.

### 3. Web UI

Open http://localhost:8000 after starting ARGO.

---

## Updating

```powershell
cd $env:LOCALAPPDATA\ARGO
.\update_argo.ps1
```

Or manually:
```powershell
git pull
pip install -r requirements.txt
```

---

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common issues:

- Python/venv problems
- Audio device issues
- Ollama connection errors
- Piper TTS failures

---

## LLM Runtime

```powershell
# Start Ollama server
ollama serve

# Pull a model (choose one)
ollama pull llama3.2      # Fast, good quality
ollama pull qwen:latest   # Alternative
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
