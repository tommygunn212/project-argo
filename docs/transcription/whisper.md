# Whisper Transcription Module

**Status:** v1.0.0 (Deterministic, Auditable)  
**Created:** January 2026  
**Creator:** Tommy Gunn (@tommygunn212)

---

## What Whisper Does

Whisper converts audio files into text **with full auditability and user confirmation**.

### Input
- WAV audio file
- Known sample rate (e.g., 16000 Hz)
- Maximum duration (default 5 minutes)
- Optional language hint

### Output
- **TranscriptionArtifact** containing:
  - Raw transcript text
  - Detected language
  - Confidence score (0.0-1.0)
  - Status (success / partial / failure)
  - Timestamp and unique artifact ID
  - Confirmation status (pending / confirmed / rejected)

### Processing
1. **Validation** (audio file exists, duration within limits)
2. **Transcription** (Whisper inference via OpenAI Whisper)
3. **Artifact Creation** (encapsulate all metadata)
4. **User Confirmation** (display text, wait for approval)
5. **Logging** (all outcomes recorded)

---

## What Whisper Explicitly Does NOT Do

**Whisper is transcription-only. It does NOT:**

- ✗ Detect intent from transcribed text
- ✗ Execute commands based on transcription
- ✗ Listen in background without user action
- ✗ Retry transcription silently on failure
- ✗ Auto-save transcriptions to long-term memory
- ✗ Process transcriptions without user confirmation
- ✗ Make assumptions about what text means
- ✗ Trigger any downstream actions automatically

---

## Architecture

### Classes

#### `TranscriptionArtifact`
Lightweight object representing a single transcription event.

```python
artifact = TranscriptionArtifact()

# Populated during transcription:
artifact.id                    # Unique UUID
artifact.timestamp             # ISO 8601 when transcription occurred
artifact.source_audio          # Path to input WAV file
artifact.transcript_text       # Raw transcription from Whisper
artifact.language_detected     # Detected language code
artifact.confidence            # 0.0-1.0 quality proxy
artifact.status                # "success" | "partial" | "failure"
artifact.error_detail          # Explanation if status != success
artifact.confirmation_status   # "pending" | "confirmed" | "rejected"
```

#### `WhisperTranscriber`
Encapsulates Whisper model loading and inference.

```python
transcriber = WhisperTranscriber(model_name="base", device="cpu")
artifact = transcriber.transcribe(
    audio_path="/path/to/audio.wav",
    max_duration_seconds=300,
    language="en"
)
```

#### `TranscriptionStorage`
Session-only storage for artifacts (no auto-save to memory).

```python
from transcription import transcription_storage

# Store artifact
transcription_storage.store(artifact)

# Retrieve by ID
artifact = transcription_storage.retrieve(artifact_id)

# User confirmation
transcription_storage.confirm(artifact_id)
transcription_storage.reject(artifact_id)

# List pending confirmations
pending = transcription_storage.list_pending()
```

### Functions

#### `transcribe_audio()`
Standalone transcription without maintaining model state.

```python
from transcription import transcribe_audio

artifact = transcribe_audio(
    audio_path="/path/to/audio.wav",
    max_duration_seconds=300,
    language="en",
    model_name="base",
    device="cpu"
)

if artifact.status == "success":
    print(f"Transcript: {artifact.transcript_text}")
    print(f"Confidence: {artifact.confidence:.2f}")
else:
    print(f"Error: {artifact.error_detail}")
```

---

## Confirmation Gate in ARGO

### User Flow

1. **User provides audio** (via voice command, file upload, etc.)
2. **Whisper transcribes** → artifact created
3. **ARGO displays:**
   ```
   Here's what I heard:
   '<transcript_text>'
   
   Proceed? (yes/no)
   ```
4. **User confirms or rejects**
5. **Only confirmed transcripts** flow to downstream processing
6. **Rejected transcripts** logged but not used

### Code Example

```python
from transcription import transcribe_audio, transcription_storage

# Transcribe
artifact = transcribe_audio("user_audio.wav")

if artifact.status == "failure":
    print(f"❌ Transcription failed: {artifact.error_detail}")
    return

# Display and request confirmation
print(f"\nHere's what I heard:")
print(f"'{artifact.transcript_text}'")
print(f"\nProceed? (yes/no): ", end="")

response = input().strip().lower()

if response in ["yes", "y"]:
    transcription_storage.confirm(artifact.id)
    # Now safe to use: artifact.transcript_text
    process_confirmed_text(artifact.transcript_text)
else:
    transcription_storage.reject(artifact.id)
    print("Transcript rejected. Please try again.")
```

---

## Failure Handling

All failures are **explicit and logged**.

### Failure Cases

| Scenario | Status | Error Detail | Action |
|----------|--------|--------------|--------|
| Audio file not found | `failure` | "Audio file not found: ..." | Prompt user to provide valid file |
| Audio exceeds max duration | `failure` | "Audio duration 302.5s exceeds max 300s" | Ask user to provide shorter clip |
| Audio format invalid | `failure` | "Failed to validate audio duration: ..." | Ensure file is WAV, correct format |
| Whisper inference fails | `failure` | "Whisper inference failed: ..." | Check Whisper model installation |
| Empty transcription | `partial` | "Whisper returned empty transcript" | Suggest re-recording (too quiet, etc.) |
| User rejects text | - | - | `confirmation_status = "rejected"` |

### Logging

All transcription events logged to `runtime/audio/logs/transcription.log`:

```
2026-01-17T14:32:45.123456Z - WHISPER - INFO - [artifact-id] Transcribing: user_audio.wav
2026-01-17T14:32:47.456789Z - WHISPER - INFO - [artifact-id] Transcription complete. Text: Hello world... Language: en Confidence: 0.95
2026-01-17T14:32:48.000000Z - WHISPER - INFO - Confirmed artifact: artifact-id
```

---

## Installation

### Prerequisites

```bash
pip install openai-whisper
```

### Usage

```python
from wrapper.transcription import transcribe_audio, transcription_storage

# Transcribe
artifact = transcribe_audio("audio.wav")

# Handle result
if artifact.status == "success":
    print(f"Transcript: {artifact.transcript_text}")
    print(f"Language: {artifact.language_detected}")
    print(f"Confidence: {artifact.confidence:.2f}")
elif artifact.status == "partial":
    print(f"Partial: {artifact.transcript_text}")
    print(f"Warning: {artifact.error_detail}")
else:
    print(f"Failed: {artifact.error_detail}")
```

---

## Testing

Test cases documented in `test_whisper_module.py`:

1. **Clean Speech** - Clear audio, normal speaking pace
2. **Background Noise** - Audio with ambient noise, other speakers
3. **Long Pauses** - Extended silence within audio
4. **Short Commands** - Single-word or phrase transcription
5. **Failure Cases** - Missing file, invalid format, exceeded duration

---

## Design Principles

### 1. Determinism
Whisper transcription is deterministic (same audio → same text).

### 2. Auditability
Every transcription event logged with artifact ID, timestamp, status.

### 3. Reversibility
User confirms text before downstream use. No blind automation.

### 4. Simplicity
Whisper does ONE thing: convert audio → text.

### 5. Failures Are Explicit
No silent retries. All errors reported.

### 6. No Memory Auto-Save
Transcriptions stored temporarily in session. Not auto-saved to long-term memory.

---

## Future Expansion

This module is designed as a foundation for:

1. **Transcription Artifacts** → **Intent Artifacts** (next phase)
2. **Voice Commands** (intent + confirmation → action)
3. **Multi-Speaker Transcription** (explicit speaker labeling)
4. **Real-Time Streaming** (as transcription happens)

No refactor needed. Extend from this base.

---

## FAQ

**Q: Why require confirmation?**  
A: Users must see what Whisper heard before it's used. Prevents blind automation.

**Q: Why no retry on failure?**  
A: Retries hide problems. Better to fail loudly and let user re-record.

**Q: Does this save to memory?**  
A: No. Transcription artifacts are session-only. If you want to save a transcript, do it explicitly.

**Q: Can Whisper execute commands?**  
A: No. Whisper transcribes only. Intent detection and action execution are separate systems.

**Q: What languages does Whisper support?**  
A: 99+ languages. Whisper auto-detects or you can hint the language.

---

## References

- [OpenAI Whisper GitHub](https://github.com/openai/whisper)
- [Whisper API Documentation](https://github.com/openai/whisper/blob/main/README.md)
- ARGO Architecture: [docs/architecture/](../architecture/)
