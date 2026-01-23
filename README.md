
# Meet ARGO: Your Local Voice AI

**ARGO** stands for **A**utonomous **R**esponse and **G**uidance **O**perator.

ARGO is a voice assistant you can truly call your own. It runs entirely on your computer—no cloud, no subscriptions, no hidden data collection. ARGO listens for your voice, understands what you want, and responds—all in real time, right where you are.

**Why ARGO?**
- You stay in control: Everything happens locally.
- It’s simple and predictable: No surprises, no runaway conversations.
- Built for clarity: Every step is transparent and easy to debug.

**Where is ARGO going?**
Our dream is for ARGO to become more than just a voice assistant. Imagine ARGO learning from you and building its own new features—like creating a custom “morning routine” when it notices you always ask for the weather and news at breakfast, or inventing a new voice command to play your favorite playlist when you get home.

**Cool Examples:**
- ARGO could notice you often say, “Remind me to call Mom on Sundays,” and offer to build a “Sunday Reminder” feature for you—no coding required.
- In the future, ARGO might gain vision capabilities, letting you ask, “What’s on my desk?” or “Did I leave the lights on?” and get real answers.
- ARGO could even build a full-featured to-do list program with reminders, deadlines, and voice-activated checklists—designed around your habits and needs.
- As ARGO grows, it could invent entirely new tools, like helping you organize your day, track your goals, or automate complex tasks, all by learning from how you use it.

**✅ PRODUCTION READY — A fully functional, bounded voice-first AI system that stays under your control.**

ARGO is a production voice assistant that prioritizes **stability, clarity, and debuggability** over features.

- **Local-first** — All processing happens on your PC (no cloud, no fees)
- **Bounded** — Max 3 interactions per session, clean exit
- **Stateless** — No memory between turns, no context carryover
- **Deterministic** — Wake word detection, intent classification, response generation, and audio playback are all predictable
- **Debuggable** — Every decision is logged and auditable
- **No squeal** — Piper TTS (offline) eliminates acoustic feedback

## What ARGO Does

ARGO processes voice through a **complete 9-stage pipeline**:

```
[1. InputTrigger]        — Porcupine wake word detection ("hello"/"computer")
        ↓
[2. DynamicRecording]    — Record audio until 1.5s silence (max 15s)
        ↓
[3. SpeechToText]        — Whisper transcription (16kHz → text)
        ↓
[4. IntentParser]        — Rule-based classification (COMMAND/QUESTION/GREETING/MUSIC/UNKNOWN)
        ↓
[5. MusicResolver]       — Alias/era/fuzzy/LLM-parse cascade (MUSIC intents only)
        ↓
[6. ResponseGenerator]   — Qwen LLM via Ollama (2000 token budget)
        ↓
[7. OutputSink (Piper)]  — Local TTS synthesis (22.05kHz PCM, NO squeal)
        ↓
[8. InterruptDetection]  — Monitor for voice activity during playback
        ↓
[9. Coordinator v4]      — 3-interaction loop + session memory + latency profiling
```

**How it works:**

1. System waits for wake word ("hello" or "computer")
2. Upon detection, records audio until 1.5 seconds of silence detected (max 15s)
3. Transcribes audio to text (Whisper, CPU-optimized)
4. Classifies intent (rule-based: COMMAND, QUESTION, GREETING, MUSIC, or UNKNOWN)
5. Resolves music requests via alias/era/fuzzy cascade (local index is authority)
6. Generates response via Qwen LLM (local Ollama, temperature=0.7, max=2000 tokens)
7. Synthesizes response via Piper TTS (local, 22.05kHz, no cloud dependency)
8. Monitors for user interruption during playback
9. Repeats up to 2 more times OR exits if response contains stop keyword (stop, goodbye, quit, exit)

## What's Fixed (January 20, 2026)

| Issue | Status | Fix |
|-------|--------|-----|
| Audio squeal on all devices | ✅ FIXED | Switched from Edge-TTS to Piper (offline, no feedback loop) |
| "Sure" response truncation | ✅ FIXED | Fixed async/sync boundary bug + increased token budget to 2000 |
| Commands not executing | ✅ FIXED | Added performance words priority rule (count/sing/recite/spell) |
| 6-second fixed recording waste | ✅ FIXED | Dynamic silence detection (1.5s threshold, max 15s) |
| No interrupt capability | ✅ FIXED | Added voice activity monitoring during playback |
| Incomplete TTS playback | ✅ FIXED | Wait for complete audio from Piper before playback |

## Recent Fixes (January 22, 2026)

| Issue | Status | Fix |
|-------|--------|-----|
| Centralized timeout policy | ✅ FIXED | Added core/policy.py for LLM/TTS/audio timeout constants |
| Silent-failure guardrails | ✅ FIXED | Added watchdogs + NO_OUTPUT detection with safe fallback |
| Empty music index crash | ✅ FIXED | Defensive handling for empty music catalog |
| Qwen 3 speed test timeout | ✅ FIXED | Model-specific timeout handling and reporting |
| Transcription contract gaps | ✅ FIXED | transcribe_and_confirm always returns an artifact |
| Music intent resolution | ✅ FIXED | Alias/era/fuzzy cascade + no random fallback |

## Performance

**Latency Breakdown (averaged over 3 interactions):**
- Recording: ~1.5s (dynamic, was 6s fixed)
- Transcription (Whisper): ~562ms
- Intent parsing: <1ms
- LLM generation (Ollama): ~1.3s
- TTS synthesis (Piper): ~5.6s
- **Total:** ~9 seconds (wake → response)

**Latency Reality (Expected):**
This timing is normal for a local CPU LLM, a serial pipeline, and non-streaming TTS. It is not a bug.

**Audio Quality:**
- Piper TTS: 22.05 kHz, full response playback (7-8 seconds for long sentences)
- Zero truncation: Full "Counting to ten: one, two, three, four, five, six, seven, eight, nine, ten" ✅
- Zero squeal: All output devices (Brio silent, M-Audio clean, DELL display clean) ✅

### What We Tried and Rejected

| Approach | Problem | Why Rejected |
|----------|---------|--------------|
| Single monolithic loop | Lost predictability; hard to debug | Can't reason about boundaries |
| Ad-hoc audio piping | Latency unpredictable; lifecycle unclear | No guarantees on timing or cleanup |
| Wake word + raw LLM | No intent classification; LLM treats all input equally | Bloated responses, poor safety |
| Implicit memory | Context leaked between turns; hard to reason about | Violated statelessness principle |
| Overloaded Coordinator | Coordinator did audio, intent, AND orchestration | Debugging impossible; tight coupling |
| Wake word detection in pure Python | Unreliable; missed detections | Need proven technology |
| HTTP polling instead of real transport | Packet loss; timing unpredictable | Audio is unreliable without RTC |

### What We Chose (And Why)

**1. Porcupine (Wake Word Detection)**
- Local, deterministic, offline
- Requires access key (security feature, not a limitation)
- Proven in production systems
- Single responsibility: detect wake word, nothing else

**2. LiveKit (Audio Transport)**
- Real RTC protocol, not ad-hoc audio piping
- Handles packet loss, jitter, timing
- Separates transport concerns from application logic
- Local server available, no cloud required

**3. Whisper (Speech-to-Text)**
- Local, open-source, reliable
- Base model is fast enough for bounded sessions
- No external API dependency

**4. Rule-Based Intent Parser**
- Explicit, debuggable classification
- No ML layer (keeps complexity low)
- Deterministic: same input → same output
- Easy to extend

**5. Qwen LLM (Ollama)**
- Local LLM, no cloud
- Isolated in single module (`ResponseGenerator`)
- Temperature, token limits, and prompts hardcoded
- Not for autonomous execution (just response generation)

**6. Piper (Text-to-Speech)**
- Offline TTS, local synthesis
- Consistent quality
- Fast enough for real-time feedback

**7. Bounded Coordinator Loop**
- Max 3 interactions hardcoded
- Clear stop conditions (stop keyword or max reached)
- No memory between turns (each turn fresh)
- Prevents runaway loops

### Design Philosophy

**Boundaries First**

Every layer has explicit boundaries. What it does. What it doesn't do. Why.

```
InputTrigger:       "I detect wake words. That's it."
SpeechToText:       "I transcribe audio. That's it."
IntentParser:       "I classify intent. That's it."
ResponseGenerator:  "I generate responses via LLM. That's it."
OutputSink:         "I speak text and handle audio transport. That's it."
Coordinator v4:     "I orchestrate the loop and enforce bounds. That's it."
```

**Dumb Layers Before Smart Layers**

- Wake word detection (dumb, deterministic)
- Transcription (dumb, deterministic)
- Intent classification (dumb, rule-based)
- Response generation (smart, LLM-based)

Each layer is as dumb as possible. Only the `ResponseGenerator` uses an LLM. Nothing else.

**Intelligence Contained, Not Distributed**

The LLM lives in exactly one place: `core/response_generator.py`. All LLM logic, prompts, temperature settings, token limits. Single file. Single responsibility.

Coordinator doesn't call LLM. InputTrigger doesn't use LLM. SpeechToText doesn't use LLM. Only ResponseGenerator talks to Ollama.

**Prefer Boring, Replaceable Components**

Every layer can be swapped:
- Replace Porcupine with different wake word engine
- Replace Whisper with different STT
- Replace rule-based parser with ML classifier
- Replace Qwen with different LLM
- Replace Edge-TTS with different TTS
- Replace LiveKit with different transport

Because each layer is isolated.

## Getting Started

### Prerequisites

- Python 3.10+
- `porcupine` (wake word detection)
- `pvporcupine` (Porcupine Python SDK)
- `openai-whisper` (speech-to-text)
- `piper-tts` (text-to-speech)
- `livekit` (RTC transport)
- `ollama` (local LLM server running on localhost:11434)

### Install

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

You need a Porcupine access key from https://console.picovoice.ai (free account):

**Option A (Temporary, this session only):**
```powershell
$env:PORCUPINE_ACCESS_KEY = "your_access_key_here"
```

**Option B (Persistent, all future sessions):**
```powershell
setx PORCUPINE_ACCESS_KEY "your_access_key_here"
# Close and reopen PowerShell
```

Also download your custom "argo" wake word model from the Picovoice console and extract it to `porcupine_key/` folder.

### Run

```powershell
$env:PYTHONPATH = $PWD
.\.venv\Scripts\python.exe legacy\run_coordinator_v4.py
```

The system will:
1. Initialize all 7 layers
2. Wait for wake word "argo"
3. Record 3 seconds of audio upon detection
4. Transcribe, classify, generate response, and speak
5. Loop up to 3 times total
6. Exit cleanly when done

## Architecture

**7-Layer Pipeline** (each layer isolated, single responsibility):

1. **InputTrigger** (`core/input_trigger.py`) — Porcupine wake word detection
2. **SpeechToText** (`core/speech_to_text.py`) — Whisper transcription
3. **IntentParser** (`core/intent_parser.py`) — Rule-based classification
4. **ResponseGenerator** (`core/response_generator.py`) — Qwen LLM response generation
5. **MusicResolver** (`core/music_resolver.py`) — Alias/era/fuzzy resolution for music requests
6. **OutputSink** (`core/output_sink.py`) — Piper TTS audio output
7. **Coordinator v4** (`core/coordinator.py`) — Bounded interaction loop
8. **Run Script** (`legacy/run_coordinator_v4.py`) — Initialization and teardown

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed layer responsibilities and design decisions.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Detailed layer design, "What We Tried and Rejected" section
- **[MILESTONES.md](MILESTONES.md)** — Project roadmap and future capabilities
- **[docs/TODO.md](docs/TODO.md)** — Post-validation backlog (API readiness, test hygiene, policy alignment)
- **[docs/coordinator_v3.md](docs/coordinator_v3.md)** — Bounded loop implementation
- **[docs/response_generator.md](docs/response_generator.md)** — LLM response generation
- **[docs/speech_to_text.md](docs/speech_to_text.md)** — Whisper integration
- **[docs/intent_parser.md](docs/intent_parser.md)** — Intent classification logic
- **[docs/ADVANCED_MUSIC_SEARCH.md](docs/ADVANCED_MUSIC_SEARCH.md)** — Music resolver cascade + alias behavior
- **[music_aliases.json](music_aliases.json)** — Human shorthand alias map for music resolution

## Key Design Constraints

1. **Max 3 interactions per session** — Hardcoded in Coordinator v3
2. **No memory between turns** — Each interaction is completely independent
3. **Deterministic** — Same input produces same output (given same LLM state)
4. **Bounded** — Always exits, never runaway
5. **Stateless voice mode** — No conversation history injection
6. **Stop keywords enforced** — Response containing "stop", "goodbye", "quit", or "exit" terminates session

## What ARGO Does NOT Do

- **Autonomous execution** — ARGO generates responses, nothing more
- **Multi-turn memory** — Each session is fresh, no context carryover
- **Background listening** — Requires wake word detection
- **Tool/Function calling** — ARGO doesn't execute code or external commands
- **Personality/Identity** — Generic responses, no character modeling
- **Cloud dependencies** — Everything runs locally

## Testing

Run the simulated test suite to verify the bounded loop:

```powershell
python test_coordinator_v3_simulated.py
```

Expected output: 3/3 tests passing
- Test 1: Verify max interactions respected
- Test 2: Verify stop keyword exits early
- Test 3: Verify independent turns

## Future Roadmap

See [MILESTONES.md](MILESTONES.md) for planned capabilities:

- **Milestone 2: Session Memory** — Optional context across turns (opt-in, explicit)
- **Milestone 3: Multi-Room / Multi-Device** — Coordinator runs on multiple devices simultaneously
- **Milestone 4: Personality Layer** — Custom voice personas (last, optional)

Each milestone is scoped to avoid regression and maintain debuggability.

## License

ARGO is open-source. See [LICENSE](LICENSE) for details.

## Credits

**Tommy Gunn** — Creator and architecture  
**January 2026** — v1.0.0 release

---

**Status: v1.0.0 — Production-ready, bounded voice system**

All 7 layers tested and validated. Wake word detection active with custom "argo" model. End-to-end operation verified.
