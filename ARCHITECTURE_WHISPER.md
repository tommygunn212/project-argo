# Whisper Integration Architecture

**Baseline:** argo-whisper-v1.0 (January 15, 2026)

## What Exists

- **whisper.cpp built locally** at `I:\argo\whisper.cpp\build\bin\Release\whisper-cli.exe`
- **Model file only:** `ggml-base.en.bin` (English, base model)
- **Python wrapper:** `system/speech/whisper_runner.py`
  - Single public function: `transcribe(audio_path: str) -> str`
  - No optional flags
  - No configuration
  - API is frozen
- **ARGO integration:** `wrapper/argo.py`
  - Tool: `transcribe_audio` (registered in TOOLS dict)
  - Non-dangerous operation (no user confirmation required)
  - Handler delegates to wrapper
- **CPU-only execution**
  - No GPU support
  - Reproducible results across machines
  - ~2.3 seconds per 11-second audio file (CPU)

## What Does NOT Exist (By Design)

- **No microphone capture** - audio must be a file on disk
- **No streaming audio** - complete files only
- **No GPU acceleration** - intentionally disabled for stability
- **No auto-transcription** - requires explicit tool call
- **No background listeners** - single-threaded, blocking calls only
- **No persistence** - no transcript caching or history beyond ARGO session logs

## Contract Rules

**Wrapper API is frozen.** To request new functionality:
- Do NOT modify `transcribe(audio_path)` signature
- Create a new function if language, VAD, or other options are needed

**Tool requires explicit user intent.** ARGO will not:
- Auto-transcribe attachments
- Infer audio file paths from context
- Store transcriptions separately from session logs

**ARGO never calls transcription autonomously.** Transcription only happens when:
- User explicitly requests it via ARGO prompt
- User calls tool: `TOOL_CALL: transcribe_audio args: audio_path: /path/to/audio.wav`
- A tool handler intentionally invokes the wrapper

---

**Known Good Baseline:** `git tag argo-whisper-v1.0`  
**Verify with:** `python test_whisper_wrapper.py`  
**Last Verified:** January 15, 2026
