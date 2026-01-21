# ARGO Setup Guide for GitHub Users

## Quick Start (5 minutes)

### 1. Clone the Repository
```powershell
git clone https://github.com/tommygunn212/argo.git
cd argo
```

### 2. Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Get Your Porcupine Access Key
1. Go to https://console.picovoice.ai
2. Sign up (free tier available)
3. Create an AccessKey for the Porcupine wake word engine
4. Copy your access key

### 5. Configure ARGO
```powershell
copy config.json.template config.json
```

Edit `config.json`:
```json
{
  "wake_word": {
    "access_key": "PASTE_YOUR_KEY_HERE"
  },
  "music": {
    "library_path": "PATH_TO_YOUR_MUSIC_FOLDER"
  }
}
```

### 6. Download Voice Models
The system will auto-download on first run, or manually:
```powershell
python -c "from transformers import WhisperProcessor, WhisperForConditionalGeneration; WhisperProcessor.from_pretrained('openai/whisper-base')"
```

### 7. Run ARGO
```powershell
.\.venv\Scripts\python.exe run_coordinator_v2.py
```

Say **"Picovoice"** to trigger, then speak your command:
- "Count to five"
- "Tell me a joke"
- "Play rock music"

---

## Configuration Details

### Required Settings

| Setting | File | Example |
|---------|------|---------|
| Porcupine Key | `config.json` | `wake_word.access_key` |
| Music Path | `config.json` | `music.library_path` |

### Optional Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `audio.device_name` | Auto-detect | Specific audio device (leave null for auto) |
| `text_to_speech.voice` | lessac | TTS voice name |
| `llm.base_url` | localhost:11434 | Ollama endpoint |
| `coordinator.max_interactions` | 10 | Max commands per session |

---

## Troubleshooting

### "No microphone detected"
- Check device in system audio settings
- Update `config.json`: `audio.device_name: "Your Device Name"`

### "Ollama connection failed"
- Install Ollama: https://ollama.ai
- Start it: `ollama serve`
- Run ARGO in another terminal

### "Porcupine key invalid"
- Get a new key: https://console.picovoice.ai
- Make sure it's for the **Porcupine** product (not Rhino)

### "Music not found"
- Set correct path in `config.json`: `music.library_path`
- Ensure songs have proper ID3 tags (artist/title)
- Run metadata fixer if needed: `python tools/metadata_fixer.py`

---

## Features

✅ **Wake Word Detection** - Say "Picovoice" to trigger  
✅ **Voice Commands** - "Count to X", "Play [artist]", Questions  
✅ **Music Playback** - Local library with genre/artist search  
✅ **LLM Responses** - Conversational Q&A  
✅ **Session Memory** - Remembers context across commands  
✅ **Offline** - No cloud dependencies (except optional LLM)

---

## File Structure

```
argo/
├── config.json              ← YOUR SETTINGS (create from template)
├── config.json.template     ← Reference copy
├── run_coordinator_v2.py    ← Main entry point
├── core/
│   ├── config.py           ← Config loader
│   ├── coordinator.py      ← Main pipeline
│   ├── intent_parser.py    ← Command classifier
│   ├── response_generator.py ← LLM integration
│   ├── output_sink.py      ← Audio playback
│   └── command_executor.py ← Procedural commands
├── tools/
│   └── metadata_fixer.py   ← ID3 tag fixer
└── audio/
    └── piper/              ← TTS engine
```

---

## Advanced: Manual Audio Device Selection

List available devices:
```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Set in `config.json`:
```json
{
  "audio": {
    "device_name": "Your Device Name"
  }
}
```

---

## Need Help?

- GitHub Issues: https://github.com/tommygunn212/argo/issues
- Documentation: See `docs/` folder
- Debug Mode: Set `system.debug_mode: true` in config.json

---

Happy voice commanding! 🎤
