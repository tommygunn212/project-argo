# Speech-to-Text (STT) Module

## Objective

Isolated boundary layer that converts audio into text.

**Single responsibility**: Audio → Text

Nothing more.

---

## What SpeechToText Does

| Action | Status |
|--------|--------|
| Accept audio bytes | ✅ YES |
| Parse sample rate | ✅ YES |
| Run transcription | ✅ YES |
| Return text | ✅ YES |
| Exit cleanly | ✅ YES |

---

## What SpeechToText Does NOT Do

| Behavior | Status | Why |
|----------|--------|-----|
| Detect wake words | ❌ NO | That's InputTrigger |
| Parse intent/meaning | ❌ NO | That's a future NLU layer |
| Generate responses | ❌ NO | That's OutputSink |
| Wire to Coordinator | ❌ NO | Will happen in next task (TASK 9) |
| Retry on failure | ❌ NO | Single attempt, no loops |
| Stream transcription | ❌ NO | One transcribe() call = one complete result |
| Maintain memory | ❌ NO | Stateless (no conversation history) |
| Add personality | ❌ NO | Just plain transcription |
| Handle microphone setup | ⚠️ CALLER'S JOB | Test script handles audio capture |

---

## Implementation: WhisperSTT

### Model Selection

- **Engine**: OpenAI Whisper (local)
- **Model Size**: `base` (reasonable accuracy ↔ speed tradeoff)
- **No Cloud**: All processing happens locally
- **Hardcoded Settings**: Predictability over flexibility
  - Language: English only
  - No language detection
  - No confidence scoring
  - No streaming mode

### Interface

```python
class SpeechToText(ABC):
    def transcribe(self, audio_data: bytes, sample_rate: int) -> str:
        """Convert audio bytes to text."""
        pass
```

### Input Format

- **Audio**: Raw WAV bytes (16-bit PCM)
- **Sample Rate**: 16000 Hz (standard)
- **Channels**: Mono (converted if stereo)
- **Duration**: Anything from 1 second to minutes

### Output Format

- **Text**: Single string
- **Encoding**: UTF-8
- **Normalized**: Whitespace trimmed
- **No Metadata**: Just plain text

---

## Usage

### Basic Example

```python
from core.speech_to_text import WhisperSTT
from scipy.io import wavfile
import io

# Initialize (loads model on first run)
stt = WhisperSTT()

# Load audio (or capture from mic)
sample_rate, audio = wavfile.read("speech.wav")

# Convert to bytes
audio_bytes = io.BytesIO()
wavfile.write(audio_bytes, sample_rate, audio)

# Transcribe (blocking, one result)
text = stt.transcribe(audio_bytes.getvalue(), sample_rate)

print(text)  # "hello world"
```

### Test Script

```bash
python test_speech_to_text_example.py
```

Records 5 seconds from microphone → transcribes → prints → exits.

---

## Isolation: Why It's Separate

### Separation of Concerns

```
InputTrigger (TASK 6)  ← Wake word detection only
    ↓
SpeechToText (TASK 8)  ← Transcription boundary
    ↓
[Future] Intent Parser ← Meaning extraction
    ↓
OutputSink (TASK 5)    ← Audio output
```

Each layer has one job:
- InputTrigger: "Did you hear the wake word?"
- **SpeechToText: "What did the user say?"**
- Intent Parser: "What does that mean?"
- OutputSink: "Speak this response"

### Design Philosophy

**Why not put transcription inside Coordinator?**

- Coordinator is pure wiring (no logic)
- STT is heavy compute (GPU, memory)
- STT deserves its own abstraction (easy to swap)
- Future: Switch from Whisper → faster-whisper without breaking Coordinator

**Why not bundle with InputTrigger?**

- InputTrigger detects wake words (lightweight)
- SpeechToText processes full speech (heavyweight)
- Different responsibilities, different lifecycles
- InputTrigger runs continuously; SpeechToText runs on-demand

---

## Future Wiring (TASK 9)

### Current Flow (Isolated)

```
[Microphone] → SpeechToText → [Print to console]
```

### Future Flow (Integrated)

```
InputTrigger (wake detected)
    ↓
[Capture audio] ← New layer (TASK 9)
    ↓
SpeechToText (transcribe)
    ↓
IntentParser (extract meaning)
    ↓
ResponseGenerator (LLM)
    ↓
OutputSink (speak)
```

### How Wiring Happens

1. **TASK 9**: Create `AudioCapture` boundary (between trigger and STT)
2. **TASK 10**: Create `Orchestrator` layer (chains all boundaries)
3. **Coordinator stays the same**: Still pure wiring (won't change)

---

## Hardcoded Choices

| Choice | Value | Rationale |
|--------|-------|-----------|
| STT Engine | Whisper (base) | Local, accurate, reasonable speed |
| Model Size | base | Smaller than large, faster than tiny |
| Language | English only | Hardcoded for predictability |
| Sample Rate | 16000 Hz | Standard for STT |
| Audio Format | WAV (16-bit PCM) | Universal, no compression artifacts |
| Retry Logic | None | Single attempt (caller retries if needed) |
| Streaming | None | One call = one complete transcription |

---

## Constraints Respected

✅ **Local Only**: No cloud API calls, no internet required

✅ **No Wake Word Logic**: Transcribe everything given, don't filter

✅ **No Intent Parsing**: Return raw text, no meaning extraction

✅ **No Coordinator Coupling**: Can be used standalone or integrated

✅ **Stateless**: Transcribe(x) always returns same result for same audio

✅ **Synchronous**: Blocking call (caller decides threading)

✅ **One-Shot**: Call transcribe() once, get one result

---

## Testing

### Minimal Test (test_speech_to_text_example.py)

```
1. Initialize Whisper engine
2. Record 5 seconds from microphone
3. Transcribe audio
4. Print result
5. Exit cleanly
```

**Expected Output**:
```
🎤 Recording for 5 seconds...
✅ Recorded XXXXX samples
📋 Initializing Whisper STT...
✅ Whisper loaded (base model)
⏳ Transcribing...
✅ Transcription complete

============================================================
TRANSCRIBED TEXT:
============================================================
"hello world this is a test"
============================================================

✅ SUCCESS
```

### Success Criteria

- [x] Audio recorded from microphone
- [x] Whisper model loads successfully
- [x] Transcription completes without error
- [x] Text is printed to console
- [x] Program exits cleanly (no hanging)

---

## Error Handling

### Expected Errors

| Error | Cause | Behavior |
|-------|-------|----------|
| ImportError | whisper not installed | Raise and exit |
| ValueError | Audio is empty | Raise ValueError |
| ValueError | Audio parsing fails | Raise with details |

### No Retries

- One attempt only
- Caller decides if retry is needed
- Keep it boring and predictable

---

## Future Enhancements (NOT in scope)

❌ Smaller/larger models (hardcoded base)
❌ Language detection (hardcoded English)
❌ Confidence scores (not returned)
❌ Streaming transcription (one call = one result)
❌ Cloud fallback (local only)
❌ Multi-language support (English only)

---

## Summary

| Aspect | Value |
|--------|-------|
| **What**: Audio-to-text boundary layer |
| **How**: OpenAI Whisper (base model, local) |
| **Input**: WAV bytes + sample rate |
| **Output**: Transcribed text string |
| **Isolation**: Completely standalone |
| **Future**: Plugs into orchestrator (TASK 9) |
| **Stability**: LOCKED (single-responsibility abstraction) |

---

**Status**: ✅ READY FOR INTEGRATION

The system can now transcribe what the user says.

Still no understanding. Still no response generation.

But the audio-to-text boundary is proven and waiting.
