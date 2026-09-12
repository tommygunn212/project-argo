# Voice audit repair status — 2026-09-12

This is an implementation ledger, not a completed end-to-end latency audit.
Existing unrelated edits in the working tree were preserved. Historical crash
logs and prior estimates are not evidence of present performance.

## Implemented in this repair batch

- Classic OpenAI TTS now uses `with_streaming_response.create`, closes the HTTP
  response on completion/failure/cancellation, and writes audio before EOF.
- TTS uses the AudioManager-selected output device, including short responses
  and prefetched PCM. It no longer uses global `sd.play`/`sd.stop` for playback.
- Cancellation invalidates old generations and aborts the TTS-owned output
  stream. Playback is serialized; the driver drains actual buffers instead of
  an additional estimated-duration sleep.
- Chunk resampling is now a continuous polyphase FIR with retained overlap,
  tested against full-signal convolution at 16, 24, 44.1 and 48 kHz. Its causal
  filter tail is preserved; no independent FFT boundary is introduced per chunk.
- TTS prefetch reuses its client. OpenAI and Ollama LLM clients are reused and
  receive `llm.timeout_seconds`. STT/TTS have explicit 15-second SDK idle timeouts;
  OpenAI automatic retries are disabled on these latency-sensitive paths.
  These are idle-operation timeouts, not a measured whole-turn deadline.
- Optional RAG/memory retrieval shares a five-second deadline and returns the
  available context on failure. At most one outstanding job per source is
  retained, avoiding growing queues when a dependency hangs. Python cannot
  forcibly cancel a running dependency; unfinished executor jobs can still
  delay interpreter shutdown and underlying retrieval timeouts remain important.
- Failed transcription releases STT ownership in `finally`. Failed/empty turns
  recover to LISTENING without overriding a user stop or a newer interaction.
- Sentence prefetch waits for late-arriving text while current speech plays;
  it is no longer a single `get_nowait()` opportunity before playback starts.
- Capture queue is bounded to 32 frames (~1.024 seconds at 16 kHz / 512 frames).
  Overflow keeps the newest audio and increments counters without callback I/O.
  The reader logs discontinuities and clears stale preroll. This makes overload
  bounded and visible; it cannot reconstruct speech lost during an overload.
- Removed unused unconditional Whisper `small` preload. STTEngineManager remains
  responsible for the selected engine; this does not prove local-engine native
  crash issues are resolved.

## Verification

- 44 targeted Python regression tests passed, including real pipeline orchestration
  with fake LLM/TTS providers, late-sentence overlap, cancellation, SDK settings,
  retrieval failure/deadline behavior, queue overflow, and STT failure cleanup.
- 4 Cortana JavaScript checks passed; modified Python syntax and git diff checks passed.
- One real OpenAI TTS/M-Track test: selected device 4, 44,100 Hz; phrase
  "Audio check complete. Streaming voice is ready."
  - First PCM yielded: 3,405 ms (measured).
  - First hardware-stream write invoked: 3,421 ms (measured, not audible onset).
  - HTTP iterator exhausted: 6,868 ms (measured; includes blocking playback writes).
  - Playback drained: 7,071 ms (measured).
  - One output-underflow warning was observed and remains to be investigated.
  These figures are not STT-to-LLM-to-TTS end-to-end timings or a before/after
  latency savings claim. No microphone turn was recorded for this test.

## Prior avatar repair

Hedra's retired realtime endpoint is bypassed, with local voice-driven Cortana
animation instead. Its regression tests are included above. Live microphone-to-
avatar synchronization still requires a real user turn; realistic video has not
been restored via a replacement cloud provider.

## Still open / not claimed fixed

1. Make voice-mode authority and actual audio ownership consistent end to end.
2. Remove or redesign blocking transition sound cues without audio-owner races.
3. Diagnose the observed output underrun and verify interruption on real hardware.
4. Measure a full current LiveKit and classic turn, with live-path instrumentation;
   distinguish network, endpointing, SDK events, and actual audible onset.
5. Classic endpointing/AEC redesign and safe tuning. Installed plugins are not
   equivalent to activated AEC; browser AEC differs from classic desktop capture.
6. Close out historical native-crash hypotheses only with fresh reproducible evidence.
7. Remaining startup/environment robustness across launchers; the key was present
   in Windows User environment, not missing from the machine.

The withdrawn SOURCE_UNKNOWN/pre-publication claim and absent-processing-lock
claim are not outstanding bugs. Do not implement fixes based on those claims.
