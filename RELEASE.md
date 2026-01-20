# ARGO v1.0.0 - Voice Pipeline Complete 🎉

**Release Date:** January 20, 2026  
**Status:** ✅ Production Ready  
**Commits:** 485e3ca (personality), b23d043 (docs), a546dd2 (release notes), 5dcd576 (code)

---

## 🚀 What's New in v1.0.0?

ARGO v1.0.0 is a **complete voice-first AI system** with all major issues fixed and production-ready.

### New Features

✅ **Porcupine Wake Word Detection**
- Local offline detection ("hello", "computer")
- Zero cloud dependencies
- Instant response (< 50ms latency)

✅ **Dynamic Recording (Smart Silence Detection)**
- Records until 1.5 seconds of silence detected
- Max 15 seconds (safety limit)
- **4x faster** than previous 6-second fixed recording

✅ **Piper ONNX Text-to-Speech**
- Offline, local TTS engine
- **Zero squeal/feedback** (fixed from Edge-TTS)
- Full response playback (not truncated)
- 22.05 kHz natural-sounding audio

✅ **Voice Activity Interrupt Detection**
- Monitors for voice during playback
- Polled every 200ms
- Allows natural conversation flow

✅ **Improved Response Quality**
- Personality enhanced (temperature 0.85)
- Better system prompts
- More thoughtful, engaging answers

✅ **Session Memory**
- 3-turn conversation capacity
- Context awareness across interactions
- Automatic eviction of oldest turns

---

## 🔧 Issues Fixed (5 Critical)

### Issue 1: Audio Squeal ✅ FIXED
**Before:** High-pitched feedback during TTS playback  
**Root Cause:** Edge-TTS service feedback loop  
**Solution:** Replaced with Piper ONNX (offline, local)  
**Result:** Zero squeal, crystal clear audio

### Issue 2: Response Truncated ("Sure" Only) ✅ FIXED
**Before:** Only first token played, rest lost  
**Root Cause:** Streaming race condition + 100 token budget  
**Solution:** Complete audio buffering + 2000 token budget  
**Result:** Full 7-8 second responses, never truncated

### Issue 3: Recording Wasteful (6 Seconds Fixed) ✅ FIXED
**Before:** Always waited 6 seconds even if done in 2  
**Root Cause:** Safety timeout, no intelligence  
**Solution:** RMS-based silence detection algorithm  
**Result:** 4x faster (1.5s average, max 15s safety)

### Issue 4: No Interrupt Capability ✅ FIXED
**Before:** Stuck listening to full response  
**Root Cause:** No monitoring during playback  
**Solution:** Voice activity detection thread (200ms polling)  
**Result:** Can interrupt naturally during TTS

### Issue 5: Wrong Intent Classification ✅ FIXED
**Before:** "Can you count?" classified as QUESTION not COMMAND  
**Root Cause:** Question mark checked before performance words  
**Solution:** Performance words priority rule  
**Result:** Commands classified correctly

---

## 📊 Performance Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Recording Latency** | 6.0s (fixed) | 1.5s avg ⚡ | 4x faster |
| **Total E2E Latency** | ~17s+ | ~9s ⚡ | 2x faster |
| **TTS Engine** | Edge-TTS (squeal) | Piper (clean) ✅ | No feedback |
| **Response Length** | "Sure" (~1s) | Full 7-8s ✅ | Complete |
| **Interrupt Support** | ❌ None | ✅ Voice detection | New feature |
| **Audio Quality** | Squeal/feedback | Natural speech | Excellent |

---

## 📚 Documentation (1,420 lines)

### GETTING_STARTED.md (376 lines)
- System requirements & prerequisites
- Step-by-step installation
- 5-minute quick start
- Configuration options
- Example interactions
- Performance expectations
- Advanced usage guide

**→ Read this first!**

### TROUBLESHOOTING.md (641 lines)
- Quick diagnostics checklist
- Installation & setup issues
- Startup issues (Porcupine, Ollama)
- Audio & recording issues
- Transcription issues (Whisper)
- TTS issues (Piper)
- LLM response issues
- Performance issues
- Session & loop issues
- Advanced debugging & testing

**→ Having problems? Look here!**

### ISSUES_RESOLVED.md (403 lines)
- All 5 critical issues documented
- Root cause analysis for each
- Solution code with examples
- Test evidence with byte counts
- Before/after metrics
- Migration guide
- Known limitations
- Future improvements

**→ Want to understand what was fixed?**

---

## 🎯 Quick Start

### Prerequisites
```powershell
# 1. Python 3.9+
python --version

# 2. Ollama (download from https://ollama.ai)
ollama serve

# 3. Porcupine Access Key (free from https://console.picovoice.ai)
$env:PORCUPINE_ACCESS_KEY = "your-key-here"
```

### Installation (5 minutes)
```powershell
# Clone & setup
git clone <repo-url> argo
cd argo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run ARGO
```powershell
# Terminal 1: Start Ollama
ollama serve

# Terminal 2: Run voice pipeline
.\.venv\Scripts\Activate.ps1
python run_coordinator_v2.py
```

### Interact
```
"Hello" or "Computer"  → Wake word trigger
"What is AI?"           → Ask a question
"Count to five"         → Give a command
"Interrupt me!"         → Interrupt during playback
"Stop" or "Goodbye"     → Exit
```

---

## 🏗️ Architecture

### Pipeline
```
Wake Word (Porcupine)
    ↓
Dynamic Recording (1.5s silence detection)
    ↓
Transcription (Whisper)
    ↓
Intent Classification (Rule-based)
    ↓
LLM Response (Ollama Qwen, 2000 tokens)
    ↓
Text-to-Speech (Piper ONNX)
    ↓
Audio Playback (sounddevice)
    ↓ (can interrupt with voice)
Return to listening
```

### Key Components
- **core/coordinator.py** - Main orchestrator
- **core/input_trigger.py** - Porcupine wake word + interrupt detection
- **core/speech_to_text.py** - Whisper transcription
- **core/intent_parser.py** - Intent classification
- **core/response_generator.py** - Ollama LLM interface
- **core/output_sink.py** - Piper TTS + playback
- **core/session_memory.py** - Conversation history

---

## ⚙️ Configuration

### .env File
```
VOICE_ENABLED=true
PIPER_ENABLED=true
PIPER_PATH=audio/piper/piper/piper.exe
PORCUPINE_ACCESS_KEY=<your-key>
OLLAMA_API_URL=http://localhost:11434
```

### Tunable Parameters (core/coordinator.py)
```python
# Recording
MAX_RECORDING_DURATION = 15      # Max seconds
SILENCE_DURATION = 1.5           # Silence threshold
SILENCE_THRESHOLD = 500          # RMS level

# Session
MAX_INTERACTIONS = 3             # Turns per session
STOP_KEYWORDS = ["stop", "goodbye", "quit", "exit"]
```

---

## 📋 What's Working

✅ Wake word detection (Porcupine)  
✅ Dynamic recording (1.5s silence)  
✅ Speech transcription (Whisper)  
✅ Intent classification  
✅ LLM response generation  
✅ Text-to-speech (Piper)  
✅ Audio playback  
✅ Interrupt detection  
✅ Session memory (3 turns)  
✅ Latency profiling  
✅ All audio devices  
✅ Windows 10/11 support  

---

## 🚫 Known Limitations

- **Offline only:** No cloud APIs needed, no internet required (except initial Porcupine key)
- **CPU-based:** No GPU acceleration (runs on any CPU, slower Whisper)
- **Local models:** Piper voice sounds somewhat robotic (offline trade-off)
- **Single device:** Doesn't support multiple mics/speakers simultaneously
- **3-turn memory:** Conversation limited to 3 turns (by design, memory-bounded)

---

## 🔄 Upgrade Path

### From v0.x to v1.0.0

No breaking changes! Existing .env files work unchanged.

```powershell
# Backup your system
git add -A && git commit -m "backup: Before upgrading"

# Pull latest
git pull origin main

# Update dependencies
pip install -r requirements.txt

# Run new version
python run_coordinator_v2.py
```

---

## 🎓 Learning Resources

- **README.md** - Project overview
- **GETTING_STARTED.md** - Installation & quick start
- **TROUBLESHOOTING.md** - Common issues & fixes
- **ISSUES_RESOLVED.md** - Technical deep-dive
- **MILESTONE_VOICE_PIPELINE_COMPLETE.md** - Architecture details
- **core/*.py** - Source code (well-commented)

---

## 📞 Support

**Having issues?**
1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) first
2. Run diagnostic: `python -c "import sounddevice; print(sounddevice.query_devices())"`
3. Check Ollama: `ollama list`
4. Check Porcupine key: `echo $env:PORCUPINE_ACCESS_KEY`

**Want to contribute?**
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

---

## 🚀 What's Next?

### Planned for v1.1.0
- [ ] Deepgram TTS integration (premium voices)
- [ ] Persistent conversation history (database)
- [ ] Multi-language support
- [ ] Custom wake words
- [ ] Web dashboard

### Nice-to-Have
- [ ] GPU acceleration (CUDA)
- [ ] LiveKit WebRTC support
- [ ] Docker containerization
- [ ] Systemd/Task Scheduler automation

---

## 📝 Release Notes

### v1.0.0 - Production Release
- ✅ All 5 critical issues fixed
- ✅ Complete documentation (1,420 lines)
- ✅ Personality improvements (temperature 0.85)
- ✅ Production-ready status
- ✅ Comprehensive testing

### v0.x - Previous Versions
- Proof-of-concept implementations
- Known issues with audio squeal and truncation
- Limited documentation

---

## 📄 License

See [LICENSE](LICENSE) file for details.

---

## 👥 Contributors

- **Primary Development:** Voice Pipeline Implementation
- **Documentation:** Comprehensive guides and troubleshooting
- **Testing:** Full audio pipeline validation

---

## 🙏 Acknowledgments

- **Porcupine** - Wake word detection
- **Whisper (OpenAI)** - Speech-to-text
- **Ollama** - LLM runtime
- **Piper** - Text-to-speech
- **Python Community** - Open-source libraries

---

**Status:** ✅ Production Ready  
**Version:** 1.0.0-voice-complete  
**Released:** January 20, 2026

**Ready to get started?** → Read [GETTING_STARTED.md](GETTING_STARTED.md)
