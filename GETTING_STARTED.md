# ARGO — Getting Started (Voice Pipeline)

**Complete voice-first AI system: Wake word → Record → Transcribe → LLM → Speak**

This guide walks you through setting up and running ARGO's production voice pipeline.

---

## System Requirements

- **OS:** Windows 10/11 (PowerShell preferred)
- **Python:** 3.9+ 
- **RAM:** 4GB minimum, 8GB+ recommended
- **Microphone:** Any USB audio device (Brio 500, built-in, etc.)
- **Speakers:** Any audio output device
- **Internet:** Only needed for initial Porcupine access key verification

### Hardware Tested ✅
- **Microphone:** Brio 500 USB (16kHz capture)
- **Speakers:** M-Audio M-Track (44.1kHz), DELL S2721Q display audio
- **CPU:** Intel/AMD (no GPU required)

---

## Prerequisites

Before starting, ensure you have:

### 1. Python 3.9+
```powershell
python --version
# Output: Python 3.9.x or later
```

### 2. Ollama (Local LLM Runtime)
- Download from https://ollama.ai
- Start the service:
  ```powershell
  ollama serve
  ```
- In another terminal, pull the Argo model:
  ```powershell
  ollama pull argo:latest
  # Or: ollama run argo:latest (will pull if needed)
  ```
- Verify it's running:
  ```powershell
  curl http://localhost:11434/api/tags
  ```

### 3. Porcupine Access Key
- Get free access key from https://console.picovoice.ai
- Store in environment variable:
  ```powershell
  $env:PORCUPINE_ACCESS_KEY = "your-access-key-here"
  ```
- Make it permanent (add to your PowerShell profile):
  ```powershell
  Add-Content $PROFILE "`n`$env:PORCUPINE_ACCESS_KEY = 'your-access-key-here'"
  ```

### 4. Audio Devices
Verify your microphone and speakers work:
```powershell
# List all audio devices
python -c "import sounddevice; print(sounddevice.query_devices())"

# Record 2 seconds and play back
python -c "import sounddevice as sd; import numpy as np; audio = sd.rec(32000, samplerate=16000); sd.wait(); sd.play(audio, samplerate=16000); sd.wait()"
```

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

You should see `(.venv)` at the start of your prompt.

### Step 4: Install Dependencies
```powershell
pip install -r requirements.txt
```

### Step 5: Verify Installation
```powershell
# Test imports
python -c "from core.coordinator import Coordinator; print('[OK] Coordinator imported')"
python -c "from core.input_trigger import PorcupineWakeWordTrigger; print('[OK] Porcupine imported')"
python -c "from core.output_sink import PiperOutputSink; print('[OK] Piper imported')"
```

## Quick Start (5 minutes)

### Terminal 1: Start Ollama
```powershell
ollama serve
```

Leave this running. You should see:
```
Listening on 127.0.0.1:11434
```

### Terminal 2: Run ARGO Voice Pipeline
```powershell
cd i:\argo
.\.venv\Scripts\Activate.ps1
python run_coordinator_v2.py
```

You'll see:
```
[*] Initializing pipeline layers...
[OK] All layers initialized
[*] Waiting for wake word...
    Speak 'hello' or 'computer' to trigger
```

### Now Interact With ARGO

**Step 1:** Speak the wake word
```
"Hello" or "Computer"
```
You'll hear a confirmation beep (Porcupine trigger)

**Step 2:** Ask a question or give a command
```
"Can you count to ten?"
"What time is it?"
"Tell me a joke"
"Stop"
```

**Step 3:** Wait for response
- System records until you stop speaking (1.5s of silence detected)
- Whisper transcribes your speech
- LLM generates response
- Piper synthesizes and plays audio
- System returns to listening

**Step 4:** Interrupt if desired
- Speak anytime during playback to interrupt
- System stops and returns to listening

**Step 5:** Exit the system
- Say: "stop", "goodbye", "quit", or "exit"
- Or press: Ctrl+C

## Example Interactions

### Interaction 1: Counting
```
YOU:    "Can you count to five?"
SYSTEM: [records 1.5s] [transcribes] [generates response] 
ARGO:   "Counting to five: one, two, three, four, five."
```

### Interaction 2: Interrupt
```
YOU:    "Tell me a long story about..."
ARGO:   [starts playing] "Once upon a time..."
YOU:    [interrupt by speaking] "Stop!"
SYSTEM: [stops playback immediately] [returns to listening]
```

### Interaction 3: Short Question
```
YOU:    "What is AI?"
SYSTEM: [records 1.5s] [transcribes]
ARGO:   "AI stands for Artificial Intelligence..."
```

---

## Music Playback

ARGO supports local music playback integrated with the voice pipeline.

### Setup

#### Step 1: Enable Music
Update `.env`:
```
MUSIC_ENABLED=true
MUSIC_DIR=I:\My Music
MUSIC_INDEX_FILE=data/music_index.json
```

Replace `I:\My Music` with the path to your music library.

#### Step 2: Scan Your Music Directory
```powershell
python scan_music_directory.py
```

This creates a persistent JSON index of your library. Subsequent runs scan only new files.

**Output:**
```
[MUSIC INDEX] Scanning: I:\My Music
[MUSIC INDEX] Found: 250 tracks
[MUSIC INDEX] Index saved: data/music_index.json
```

#### Step 3: Supported Formats
- `.mp3` (MPEG Audio)
- `.wav` (WAV)
- `.flac` (Free Lossless Audio Codec)
- `.m4a` (MPEG-4 Audio)

### Voice Commands for Music

Once enabled, use these voice commands during ARGO operation:

#### Play Random Track
```
YOU:    "Play music"
ARGO:   [starts playback] "Playing: Track Name by Artist"
```

#### Play Specific Artist
```
YOU:    "Play The Beatles"
ARGO:   [starts playback] "Playing: Eleanor Rigby by The Beatles"
```

#### Play Specific Song
```
YOU:    "Play Bohemian Rhapsody"
ARGO:   [starts playback] "Playing: Bohemian Rhapsody by Queen"
```

#### Play Genre
```
YOU:    "Play punk music" or "Play classic rock"
ARGO:   [starts playback] "Playing: Track Name by Artist"
```

#### Stop Music
```
YOU:    "Stop" or [speak during playback]
ARGO:   [stops immediately] [returns to listening]
```

#### Skip to Next Track
```
YOU:    "Next" or "Skip"
ARGO:   [continues in same mode] "Playing: Next Song by Same Artist/Genre"
```

#### What's Playing (Status Query)
```
YOU:    "What's playing" or "What song is this"
ARGO:   "You're listening to Song Name by Artist Name."
```

### How Music Routing Works

ARGO follows this priority when you ask to play music:

1. **Artist match** - Exact artist in your library?
2. **Song match** - Exact song title?
3. **Genre match** - Exact genre folder or tag?
4. **Keyword match** - Partial matches in metadata?
5. **Random fallback** - Pick a random track

**Example:** "Play Beatles" → Artist match → Plays random Beatles song

### Music Index Schema

The `music_index.json` contains your library metadata:

```json
{
  "tracks": [
    {
      "id": "abc123def456",
      "path": "I:\\My Music\\Rock\\The Beatles\\Eleanor Rigby.mp3",
      "name": "eleanor rigby",
      "artist": "The Beatles",
      "song": "Eleanor Rigby",
      "genre": "rock",
      "tokens": ["eleanor", "rigby", "beatles", "rock"],
      "filename": "Eleanor Rigby.mp3",
      "ext": ".mp3"
    }
  ]
}
```

**Fields:**
- `path` - Absolute path to audio file (required)
- `name` - Filename without extension (required)
- `artist` - Extracted from folder name or "Unknown"
- `song` - Extracted from filename
- `genre` - Detected from folder names (see `GENRE_ALIASES` in code)
- `tokens` - Tokenized for keyword search

### Troubleshooting Music

**"No music found"**
- Ensure `MUSIC_DIR` points to valid directory
- Run `python scan_music_directory.py` to index
- Check `.env` has `MUSIC_ENABLED=true`

**"Music disabled"**
- Check `.env`: `MUSIC_ENABLED=false`? Set to `true`
- Check `MUSIC_DIR` exists and is readable

**Files not found in scan**
- Ensure files use supported formats (`.mp3`, `.wav`, `.flac`, `.m4a`)
- Check file permissions (must be readable)
- Check path has no special characters causing encoding issues

**Music doesn't stop when speaking**
- Voice interrupt detection monitors for wake word
- Should stop within 200ms of your voice
- If not, check Porcupine access key is set

---

## Configuration


### .env File
Create or update `.env` with:
```
VOICE_ENABLED=true
PIPER_ENABLED=true
PIPER_PATH=audio/piper/piper/piper.exe
PORCUPINE_ACCESS_KEY=<your-key-from-picovoice>
OLLAMA_API_URL=http://localhost:11434

# Music playback (optional)
MUSIC_ENABLED=true
MUSIC_DIR=I:\My Music
MUSIC_INDEX_FILE=data/music_index.json
```

### Tunable Parameters (core/coordinator.py)

Edit these for different behavior:

```python
# Recording settings
MAX_RECORDING_DURATION = 15      # Max seconds to record
SILENCE_DURATION = 1.5           # Seconds of silence to stop
SILENCE_THRESHOLD = 500          # RMS level (lower = more sensitive)

# Loop settings
MAX_INTERACTIONS = 3             # Interactions per session
STOP_KEYWORDS = ["stop", "goodbye", "quit", "exit"]

# Audio settings
AUDIO_SAMPLE_RATE = 16000        # Hz (Whisper standard)
```

## Verify Everything Works

Run this diagnostic:

```powershell
# 1. Check Ollama
curl http://localhost:11434/api/tags
# Should show argo:latest in the list

# 2. Check Porcupine key
echo $env:PORCUPINE_ACCESS_KEY
# Should show your access key

# 3. Check audio devices
python -c "import sounddevice; print(sounddevice.default.device)"

# 4. Test full pipeline
python run_coordinator_v2.py
# Try: "Hello computer, can you hear me?"
# Should transcribe and respond
```

---

## Troubleshooting Quick Fixes

### "Porcupine access key not found"
```powershell
$env:PORCUPINE_ACCESS_KEY = "your-key-here"
```

### "Ollama connection refused"
```powershell
# Terminal 1
ollama serve

# Terminal 2 (new), verify it's running
ollama list
```

### "No module named 'sounddevice'"
```powershell
pip install sounddevice
```

### "Piper executable not found"
```powershell
# Verify piper exists
ls audio/piper/piper/piper.exe

# Or download it
python -m piper.download_voices --voice en_US-lessac-medium
```

### "No microphone detected"
```powershell
# List devices
python -c "import sounddevice; print(sounddevice.query_devices())"

# Use specific device (change index)
# Edit core/coordinator.py, line ~180:
# stream = sd.InputStream(device=2, ...)  # Use device index 2
```

### "Whisper model not downloaded"
```powershell
# First run downloads ~140MB model (takes a few minutes)
# Subsequent runs use cached model
# Can pre-download:
python -c "import whisper; whisper.load_model('base')"
```

## File Structure

```
argo/
├── README.md                              # Project overview
├── GETTING_STARTED.md                     # This file ✓
├── RELEASE_NOTES_v1_0_0_COMPLETE.md      # Release notes
├── MILESTONE_VOICE_PIPELINE_COMPLETE.md  # Milestone doc
│
├── run_coordinator_v2.py                  # Main entry point ⭐
├── .env                                   # Configuration
│
├── core/
│   ├── coordinator.py                     # Main orchestrator
│   ├── input_trigger.py                   # Porcupine wake word
│   ├── speech_to_text.py                  # Whisper transcription
│   ├── intent_parser.py                   # Intent classification
│   ├── response_generator.py              # Ollama LLM
│   ├── output_sink.py                     # Piper TTS + playback
│   ├── session_memory.py                  # Conversation history
│   └── latency_probe.py                   # Profiling
│
├── audio/
│   └── piper/
│       └── piper/piper.exe                # TTS executable
│       └── voices/                        # Voice models
│
├── backups/
│   └── milestone_20260120_002245/         # Snapshot
│
└── requirements.txt                       # Python dependencies
```

---

## How It Works (Under the Hood)

### The Pipeline

1. **Wake Word Detection (Porcupine)**
   - Listens continuously for "hello" or "computer"
   - Runs locally, ~0ms latency

2. **Dynamic Audio Recording**
   - Records until 1.5 seconds of silence detected
   - Max 15 seconds (safety limit)
   - Adaptive: short questions = fast recording, long explanations = full capture

3. **Speech-to-Text (Whisper)**
   - Transcribes at 16kHz mono
   - Base model on CPU: ~500-700ms

4. **Intent Classification (Rule-Based)**
   - COMMAND: "count to five" (executes)
   - QUESTION: "what is AI?" (answers)
   - GREETING: "hello" (greets)
   - UNKNOWN: fallback response

5. **LLM Response (Ollama Qwen)**
   - Generates response with 2000 token budget
   - Temperature 0.7 (balanced creativity)
   - Typical: ~1-3 seconds

6. **Text-to-Speech (Piper)**
   - Synthesizes response locally
   - 22.05 kHz audio
   - Typical: ~5-8 seconds for full response

7. **Audio Playback**
   - Plays to default speaker
   - Monitors for voice activity (interrupt detection)
   - Clean audio, zero squeal ✅

8. **Interrupt Detection**
   - Polls every 200ms during playback
   - If voice detected, stops TTS and returns to listening
   - Allows natural conversation flow

---

## Performance Expectations

### Latency Profile
- **Wake to response:** ~9 seconds total
  - Recording: 1.5s (was 6s) ⚡
  - Transcription: ~600ms
  - LLM: ~1-2s
  - TTS: ~5-7s
  - Playback: real-time

### Audio Quality
- **Sample rate:** 22.05 kHz (Piper standard)
- **Duration:** 7-8 seconds for full count response
- **Clarity:** Natural, clear speech
- **Squeal:** None (offline Piper mode) ✅

### Resource Usage
- **CPU:** 30-50% during transcription
- **RAM:** ~500MB typical
- **GPU:** Not required (CPU mode)
- **Network:** Only for initial Porcupine key check
---

## Advanced Usage

### Run with Custom Output Device
```powershell
# Edit core/coordinator.py
# In __init__, add:
import sounddevice as sd
sd.default.device = 2  # Use device index 2 (from query_devices)
```

### Change Recording Sensitivity
```powershell
# Edit core/coordinator.py
SILENCE_THRESHOLD = 300  # Lower = more sensitive (false stops)
SILENCE_THRESHOLD = 700  # Higher = less sensitive (wait longer)
```

### Extend Context Window
```powershell
# Edit core/coordinator.py
MAX_INTERACTIONS = 5     # Up to 5 turns instead of 3
```

### Use Different Voice Model
```powershell
# Edit .env
PIPER_VOICE_MODEL=en_US-libritts-high  # Different voice (if downloaded)

# Download new voice
python -m piper.download_voices --voice en_US-libritts-high
```

---

## Next Steps

1. **Explore the code:**
   - Read [MILESTONE_VOICE_PIPELINE_COMPLETE.md](MILESTONE_VOICE_PIPELINE_COMPLETE.md) for architecture
   - Check [core/coordinator.py](core/coordinator.py) for orchestration logic

2. **Monitor latency:**
   - Check console output for profiling data
   - Each interaction shows: recording, STT, LLM, TTS times

3. **Customize responses:**
   - Edit [core/intent_parser.py](core/intent_parser.py) for intent rules
   - Edit [core/response_generator.py](core/response_generator.py) for LLM prompts

4. **Deploy to production:**
   - Run as scheduled task (Windows Task Scheduler)
   - Or as service (systemd on Linux)

---

## Getting Help

- **Won't start?** → See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Audio issues?** → Check [TROUBLESHOOTING.md#audio-devices](TROUBLESHOOTING.md#audio-devices)
- **LLM not responding?** → Verify Ollama: `ollama list`
- **Squeal/feedback?** → Try different speaker device
- **Recording too short/long?** → Adjust `SILENCE_THRESHOLD` and `SILENCE_DURATION`

---

## What's Different From v0.x?

| Feature | v0.x | v1.0.0 |
|---------|------|--------|
| Wake word | ❌ | ✅ Porcupine |
| Recording | 6s fixed | 1.5s dynamic ⚡ |
| TTS | Edge-TTS (squeal) | Piper (clean) ✅ |
| Response length | "Sure" only | Full responses ✅ |
| Interrupt | ❌ | ✅ Voice detection |
| Latency | 17s+ | ~9s ⚡ |
| Squeal | ✅ (bad) | ❌ (fixed) |

---

**Status:** ✅ Production-ready  
**Last Updated:** January 20, 2026  
**Version:** v1.0.0-voice-complete

**Ready to start?** → Run `python run_coordinator_v2.py` and say "Hello!"
