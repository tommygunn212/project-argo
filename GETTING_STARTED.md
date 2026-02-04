# ARGO — Getting Started (VAD‑Only Voice Pipeline)

**Always‑listening voice system: VAD → Transcribe → LLM → Speak**

This guide walks you through setting up and running the current ARGO pipeline. The wake word has been removed by design.

---

## System Requirements

- **OS:** Windows 10/11 (PowerShell recommended)
- **Python:** 3.10+ (3.11 recommended)
- **RAM:** 8GB+ recommended
- **Microphone:** Any USB audio device
- **Speakers:** Any audio output device
- **OpenRGB:** Optional, for lighting control

---

## Prerequisites

### 1) Python
```powershell
python --version
```

### 2) Ollama (Local LLM Runtime)
Download from https://ollama.ai

Start the service:
```powershell
ollama serve
```

Pull the model:
```powershell
ollama pull qwen:latest
```

Verify it’s running:
```powershell
curl http://localhost:11434/api/tags
```

### 3) Audio Devices
Verify your microphone and speakers work:
```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```

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

## Installation

### Step 1: Clone Repository
```powershell
git clone <repository-url> argo
cd argo
```

### Step 2: Create Virtual Environment
```powershell
python -m venv .venv
```

### Step 3: Activate Virtual Environment
```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 4: Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## Quick Start

### Terminal 1: Start Ollama
```powershell
ollama serve
```

### Terminal 2: Run ARGO
```powershell
cd i:\argo
.\.venv\Scripts\Activate.ps1
python main.py
```

### Open the UI Debugger
- http://localhost:8000

---

## Expected Behavior

- ARGO continuously listens via VAD.
- When speech is detected, it transcribes, generates a response, and speaks it.
- The UI debugger shows live logs, model names, and latency metrics.

---

## System Health & Disk Queries (Deterministic)

The following are deterministic and never call the LLM:
- CPU, memory, GPU, OS, motherboard
- Drive usage and free space

Examples:
- “How full is my D drive?”
- “Which drive has the most free space?”
- “What drive is the fullest?”

---
## Voice Commands

### Silence Override ("Shut Up")
Tell ARGO to stop talking:
- "Shut up"
- "Stop talking"
- "Enough"
- "Quiet"

ARGO will deliver one joke, then enter **quiet mode** (TTS disabled).

### Identity
- "What's your name?" / "Who are you?" — triggers identity response
- "Tell me about yourself" — same

---

## Text Input (Frontend)

The frontend UI includes a text input bar for testing conversations without a microphone:

1. Open http://localhost:8000
2. Type in the input field at the bottom of the transcript area
3. Press ENTER or click SEND

**Features:**
- Bypasses STT (confidence = 100%)
- Same pipeline as voice (intent → persona → TTS)
- **Turn indicator** shows `Turn X/Y` (session limit)
- **Text barge-in**: Sending text while ARGO is speaking interrupts it

---

## Personas

ARGO supports multiple personality modes configured in `config.json`:

```json
{
  "personality": {
    "default": "tommy_gunn"
  }
}
```

Available personas:
| Persona | Style |
|---------|-------|
| `neutral` | Clean, professional |
| `tommy_gunn` | Conversational mentor |
| `rick` | Rick Sanchez (answers only) |
| `claptrap` | Borderlands robot |
| `jarvis` | Butler-like assistant |
| `plain` | No transformation |

Personas are gated by response type — system messages always stay neutral.

---
## Milestone: Music + System Health Hardening (Jan 2026)

**Why:** predictable system facts and stable music control under load.

Local music indexing is available via scripts/rebuild_music_index.py and MUSIC_SOURCE=local.

---

## Lighting Control (Optional)

Lighting commands target OpenRGB devices when these are set:

- OPENRGB_EXE=path\to\OpenRGB.exe
- OPENRGB_DEVICES=0,1

OpenRGB server must be running.

---

## Troubleshooting

### Piper not found
**Symptom:** Logs show `Piper not in PATH` or no TTS output.  
**Fix:** Install Piper and ensure it’s callable (`python -m piper` works).

### No audio output
**Symptom:** TTS logs appear but nothing plays.  
**Fix:** Verify output device selection and volume; check device list in logs.

### VAD too sensitive
**Symptom:** Frequent false triggers or interruptions.  
**Fix:** Increase the VAD threshold in `main.py`.

### STT returns empty results
**Symptom:** No transcription or garbled output.  
**Fix:** Speak closer to the mic or raise input gain.

---

## UI Debugger

The UI is the primary observability surface:
- **Status cards** show STT/LLM/TTS model names and readiness
- **Latency cards** show recent timings
- **Logs** show pipeline steps in real time

If the UI is blank or stale, check the WebSocket at ws://localhost:8001/ws.

---

## Advanced Tuning

### Change VAD Sensitivity
Adjust the VAD threshold in `main.py`:
```python
VAD_THRESHOLD = 3.0  # Higher = less sensitive
```

### Change Output Device
Set the output device in `core/audio_manager.py` or update the default output device in your OS.

---

## Next Steps

1. Review [ARCHITECTURE.md](ARCHITECTURE.md) for the current pipeline.
2. Use the UI debugger to validate model readiness and latency.
3. Tune VAD thresholds if the environment is noisy.
