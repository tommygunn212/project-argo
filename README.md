# ARGO: Local Voice System

**A predictable, bounded, voice-first AI system that stays under your control.**

ARGO is a proof-of-concept voice assistant that prioritizes **safety, clarity, and debuggability** over features.

- **Local-first** — All processing happens on your PC (no cloud)
- **Bounded** — Max 3 interactions per session, clean exit
- **Stateless** — No memory between turns, no context carryover
- **Deterministic** — Wake word detection, intent classification, response generation, and audio playback are all predictable
- **Debuggable** — Every decision is logged and auditable

## What ARGO Does

ARGO processes voice through a **7-layer pipeline**:

```
[1. InputTrigger]       — Porcupine wake word detection ("argo")
        ↓
[2. SpeechToText]       — Whisper transcription (base model, local)
        ↓
[3. IntentParser]       — Rule-based intent classification (GREETING, QUESTION, COMMAND, UNKNOWN)
        ↓
[4. ResponseGenerator]  — Qwen LLM via Ollama (localhost:11434, temp=0.7, max_tokens=100)
        ↓
[5. OutputSink]         — Edge-TTS synthesis + LiveKit audio transport
        ↓
[6. Coordinator v3]     — Bounded loop: max 3 interactions, stop on keyword
        ↓
[7. Run Script]         — Initialization and cleanup
```

**How it works:**

1. System waits for wake word "argo"
2. Upon detection, records 3 seconds of audio
3. Transcribes audio to text (Whisper)
4. Classifies intent (rule-based: greeting, question, command, or unknown)
5. Generates response via Qwen LLM (local, isolated)
6. Speaks response via Edge-TTS (Microsoft API, local synthesis)
7. Publishes audio via LiveKit (real transport, not ad-hoc piping)
8. Repeats up to 2 more times OR exits if response contains stop keyword (stop, goodbye, quit, exit)

## Why This Stack?

### Original Goal: Keep it Simple

We started with a simple philosophy: **use only the minimal pieces required for a working voice system.**

Problem: What's "minimal" became clear only through hard problems.

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

**6. Edge-TTS (Text-to-Speech)**
- Microsoft TTS API, local synthesis
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
Coordinator v3:     "I orchestrate the loop and enforce bounds. That's it."
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
- `edge-tts` (text-to-speech)
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
python run_coordinator_v3.py
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
5. **OutputSink** (`core/output_sink.py`) — Edge-TTS + LiveKit audio output
6. **Coordinator v3** (`core/coordinator.py`) — Bounded interaction loop
7. **Run Script** (`run_coordinator_v3.py`) — Initialization and teardown

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed layer responsibilities and design decisions.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Detailed layer design, "What We Tried and Rejected" section
- **[MILESTONES.md](MILESTONES.md)** — Project roadmap and future capabilities
- **[docs/coordinator_v3.md](docs/coordinator_v3.md)** — Bounded loop implementation
- **[docs/response_generator.md](docs/response_generator.md)** — LLM response generation
- **[docs/speech_to_text.md](docs/speech_to_text.md)** — Whisper integration
- **[docs/intent_parser.md](docs/intent_parser.md)** — Intent classification logic

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

**Bob** — Architecture, implementation, documentation  
**January 2026** — v1.0.0 release

---

**Status: v1.0.0 — Production-ready, bounded voice system**

All 7 layers tested and validated. Wake word detection active with custom "argo" model. End-to-end operation verified.
