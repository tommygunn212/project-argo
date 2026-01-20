# ARGO FAQ

## General Questions

### Q: What is ARGO?

**A:** ARGO is a local-first, voice-first AI system that runs on your PC. It listens for a wake word ("argo"), records audio, transcribes it, generates a response via LLM, and speaks the answer back. All processing happens locally—no cloud, no network dependency.

---

### Q: Is ARGO a full assistant?

**A:** No. ARGO is a **bounded voice system**, not a general-purpose assistant. It:
- ✅ Detects wake words
- ✅ Transcribes speech
- ✅ Classifies intent
- ✅ Generates responses (via LLM)
- ✅ Speaks answers
- ✅ Loops up to 3 interactions

It does NOT:
- ❌ Remember previous conversations
- ❌ Execute code or commands
- ❌ Control smart home devices
- ❌ Maintain state between sessions
- ❌ Understand context implicitly

---

### Q: Can I change the wake word from "argo"?

**A:** Yes. The custom "argo" wake word model is in `porcupine_key/hey-argo_en_windows_v4_0_0.ppn`. You can download a different model from Picovoice console and update `core/input_trigger.py` line 183 to use it.

---

### Q: Can I use ARGO offline?

**A:** Almost. You need:
- ✅ Local: Whisper (STT), Qwen (LLM), Edge-TTS (synthesis), LiveKit (transport), Porcupine (wake word)
- ❌ One-time: Download Porcupine access key from console.picovoice.ai (requires internet once)
- ❌ One-time: Download Whisper and Qwen models (requires internet once)

After initial setup, ARGO runs fully offline.

---

### Q: Why Porcupine for wake word detection?

**A:** Porcupine is:
- Local (runs on your device, offline)
- Deterministic (same audio = same result always)
- Proven in production
- Access key provides security/accountability

See [ARCHITECTURE.md](ARCHITECTURE.md) for full rationale.

---

## Technical Questions

### Q: Why max 3 interactions per session?

**A:** Design choice for **safety and predictability**:
- Prevents runaway loops
- Prevents memory contamination
- Keeps sessions bounded
- Clear exit condition
- Easy to debug

See [docs/coordinator_v3.md](docs/coordinator_v3.md) for design details.

---

### Q: How do I add conversation memory?

**A:** Not implemented in v1.0.0 (intentional). Milestone 2 will add optional session memory (opt-in only).

Currently, each turn is independent—no context carryover. This is a feature, not a limitation.

---

### Q: Can I run ARGO on Raspberry Pi?

**A:** Not in v1.0.0. Planned for Milestone 3 (Multi-Device).

Currently requires a PC with:
- Python 3.10+
- Windows or Linux
- USB microphone (recommended)
- 4GB+ RAM (for Ollama + Whisper)

---

### Q: How do I change the LLM from Qwen?

**A:** Replace in `core/response_generator.py`:
1. Change `model = "argo:latest"` to your model name
2. Update `ollama_endpoint` if using different server
3. Update `temperature` and `max_tokens` as needed

ResponseGenerator is isolated—swap LLM without touching other layers.

---

### Q: Why use Edge-TTS instead of Piper?

**A:** Edge-TTS offers:
- Consistent quality
- Built-in text cleaning
- No local model files needed
- Works reliably in production

Both are valid. Edge-TTS is current choice.

---

### Q: Can I add personality to responses?

**A:** Not in v1.0.0. Planned for Milestone 4 (optional).

Currently ResponseGenerator uses hardcoded neutral prompts. Future milestone will allow custom personas.

---

## Operational Questions

### Q: How do I start ARGO?

**A:**
```powershell
$env:PORCUPINE_ACCESS_KEY = "your_key_here"  # Or use setx for permanent
python run_coordinator_v3.py
```

System initializes, waits for wake word "argo", then processes 3 interactions max.

---

### Q: How do I stop the loop early?

**A:** Two methods:
1. **Response contains stop keyword:** If LLM response contains "stop", "goodbye", "quit", or "exit", loop exits
2. **Force exit:** Press Ctrl+C in terminal

---

### Q: What's the latency (time per interaction)?

**A:** Typical:
- Wake word detection: Continuous
- Audio capture: 3 seconds
- Whisper: 1-2 seconds
- Intent classification: <50ms
- Qwen inference: 2-5 seconds (depends on hardware)
- Edge-TTS: <1 second
- LiveKit publish: <100ms
- **Total per turn:** 8-12 seconds

See [ARCHITECTURE.md](ARCHITECTURE.md) for details.

---

### Q: Can I run multiple ARGO instances?

**A:** Not recommended in v1.0.0 (different port bindings needed).

Planned for Milestone 3 (Multi-Device coordination).

---

## Development Questions

### Q: Can I modify the code?

**A:** Yes. The 7-layer architecture is stable:
- Layer modifications: Easy (isolated, single-responsibility)
- Adding new layers: Easy (just wire into Coordinator)
- Swapping components: Easy (each layer replaceable)

See [ARCHITECTURE.md](ARCHITECTURE.md) for layer boundaries.

---

### Q: How do I run tests?

**A:**
```powershell
python test_coordinator_v3_simulated.py
```

Expected output: 3/3 tests passing

Tests verify:
- Max 3 interactions enforced
- Stop keyword exits early
- Independent turns (no context carryover)

---

### Q: What's the test coverage?

**A:** v1.0.0 covers:
- ✅ All 7 layers tested individually
- ✅ Integration tests (3/3 passing)
- ✅ End-to-end validated with real audio
- ✅ Loop bounds verified
- ✅ Stop keyword handling verified

---

### Q: Can I contribute?

**A:** Not yet. This is the initial v1.0.0 release.

Future: See [MILESTONES.md](MILESTONES.md) for planned enhancements and contribution opportunities.

---

## Deployment Questions

### Q: Is ARGO production-ready?

**A:** Yes, for v1.0.0 use case:
- ✅ Bounded voice system (max 3 interactions)
- ✅ Stateless (no memory contamination)
- ✅ Deterministic (predictable behavior)
- ✅ Fully tested (3/3 integration tests)
- ✅ Documented

**For other use cases:** See [MILESTONES.md](MILESTONES.md) for planned capabilities.

---

### Q: What's the license?

**A:** See [LICENSE](LICENSE) for full terms.

ARGO is open-source. Check licensing before commercial use.

---

### Q: How do I report a bug?

**A:** Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) first.

For bugs not covered there:
1. Enable debug mode: `$env:DEBUG = "true"`
2. Capture logs: `python run_coordinator_v3.py 2>&1 | Tee debug.log`
3. Provide:
   - Error message
   - Steps to reproduce
   - System info (Windows, Python version, etc.)

---

## Security Questions

### Q: Is my data private?

**A:** Yes. ARGO:
- ✅ Runs locally (no data sent anywhere)
- ✅ No cloud dependencies
- ✅ No network calls except to local Ollama, LiveKit, Porcupine (on-device)
- ✅ No recording/storage of conversations (unless you add it)

All processing stays on your PC.

---

### Q: What about the Porcupine access key?

**A:** Porcupine access key is:
- ✅ A security feature (limits who can use your custom model)
- ✅ Stored locally in environment variable (not hardcoded)
- ✅ Required only at startup

See [README.md](README.md) for setup.

---

### Q: Can ARGO listen without wake word?

**A:** No. ARGO only activates on wake word "argo". Otherwise, it's silent (no background listening, no microphone access).

This is intentional design: wake word = explicit user control.

---

## Support

**For questions not answered here:**
1. Check [README.md](README.md) — system overview
2. Check [ARCHITECTURE.md](ARCHITECTURE.md) — design rationale
3. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common issues
4. Check [docs/coordinator_v3.md](docs/coordinator_v3.md) — loop details
5. Review test file: `test_coordinator_v3_simulated.py`
