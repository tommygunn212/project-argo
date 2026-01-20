# STACK CONTRACT (v0.1)

## Wake Word
- Engine: Porcupine
- Responsibility: wake-word detection only
- Output: emit WAKE_DETECTED event
- No audio streaming
- No retries
- No fallback logic

## Transport
- Engine: LiveKit (local only)
- Responsibility: real-time audio and event transport
- Rooms: named by location (living_room, office, garage)
- Guarantees:
  - Non-blocking
  - Reconnect-safe
  - No business logic

## Speech Output
- Engine: Edge-TTS
- Responsibility: text to speech only
- Input: plain text
- Output: PCM audio streamed into LiveKit
- No caching
- No personality logic

## Non-Goals
- No cloud fallback
- No STT beyond wake word
- No intent parsing
- No assistant behavior
- No UI
- No opinions

## Rule
Each layer must be:
- Stateless
- Replaceable
- Killable without crashing others

## STOP POINT
- Commit the file
- Do not write any code
- Do not install dependencies
- Do not run tests

Wait for explicit approval before proceeding.