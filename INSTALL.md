# ARGO Installation Guide

> **Version:** 1.6.4 | **Platform:** Windows 10/11 (x64)

---

## 🚀 Quick Install (5 minutes)

### Step 1: Install Prerequisites

Before running the installer, you need **Python** and **Git** installed.

| Software | Download | Installation Notes |
|----------|----------|-------------------|
| **Python 3.11** | [python.org/downloads](https://www.python.org/downloads/) | ⚠️ **CHECK "Add Python to PATH"** during install |
| **Git** | [git-scm.com/download/win](https://git-scm.com/download/win) | Use default options |
| **Ollama** | [ollama.ai/download](https://ollama.ai/download) | For AI responses (install after ARGO) |

### Step 2: Run the Installer

1. **Open PowerShell as Administrator**
   - Press `Win + X`, then click "Windows Terminal (Admin)" or "PowerShell (Admin)"

2. **Copy and paste this command:**

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/tommygunn212/project-argo/audio-reset-phase0/install_argo.ps1 | iex"
```

3. **Wait for installation to complete** (2-5 minutes depending on internet speed)

### Step 3: Set Up Ollama

After ARGO installs, open a **new** PowerShell window and run:

```powershell
ollama serve
```

Then in **another** PowerShell window:

```powershell
ollama pull llama3.2
```

### Step 4: Start ARGO

- **Double-click the "ARGO" shortcut** on your desktop
- Or open PowerShell and run:

```powershell
cd $env:LOCALAPPDATA\ARGO
.\.venv\Scripts\Activate.ps1
python main.py
```

### Step 5: Open the Web UI

Open your browser to: **http://localhost:8000**

---

## ✅ What the Installer Does

| Step | Description |
|------|-------------|
| 1 | Verifies Python 3.10+ is installed |
| 2 | Verifies Git is installed |
| 3 | Clones ARGO to `C:\Users\YOU\AppData\Local\ARGO` |
| 4 | Creates Python virtual environment |
| 5 | Installs all required Python packages |
| 6 | Downloads Piper TTS engine (~50MB) |
| 7 | Downloads Ryan voice model (~100MB) |
| 8 | Creates config.json from template |
| 9 | Creates desktop shortcut |

---

## 🔧 Post-Install Configuration

### Audio Devices

ARGO needs to know which microphone and speaker to use.

**List your audio devices:**
```powershell
cd $env:LOCALAPPDATA\ARGO
.\.venv\Scripts\Activate.ps1
python -c "import sounddevice; print(sounddevice.query_devices())"
```

**Edit config.json** with your device numbers:
```json
{
    "audio": {
        "input_device_index": 1,
        "output_device_index": 2
    }
}
```

### API Keys (Optional)

| Key | Purpose | Get it from |
|-----|---------|-------------|
| `PORCUPINE_ACCESS_KEY` | Wake word ("Hey ARGO") | [picovoice.ai](https://picovoice.ai) |
| `OPENAI_API_KEY` | Cloud speech recognition | [platform.openai.com](https://platform.openai.com) |

Add to your environment or config.json.

---

## 🔄 Updating ARGO

To get the latest version:

```powershell
cd $env:LOCALAPPDATA\ARGO
.\update_argo.ps1
```

---

## ❌ Common Problems

### "Python is not recognized"

Python wasn't added to PATH during installation.

**Fix:** Reinstall Python and **CHECK the "Add Python to PATH" box**.

### "Git is not recognized"

Git isn't installed.

**Fix:** Download and install from [git-scm.com](https://git-scm.com/download/win)

### "Scripts cannot be run on this system"

PowerShell is blocking scripts.

**Fix:** Run this first:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "Connection refused" or "Ollama not running"

Ollama server isn't running.

**Fix:** Open a separate PowerShell window and run:
```powershell
ollama serve
```

### No sound / wrong microphone

Audio devices not configured.

**Fix:** See "Audio Devices" section above.

### For more issues

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — 850+ lines of detailed fixes.

---

## 📁 Installation Location

ARGO installs to:
```
C:\Users\YOUR_USERNAME\AppData\Local\ARGO\
```

You can find this by typing `%LOCALAPPDATA%\ARGO` in File Explorer.

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
