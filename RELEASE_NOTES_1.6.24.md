# ARGO Release Notes — v1.6.24 (February 2026)

**Combined release covering v1.6.20 through v1.6.24**

---

## Highlights

- 🎭 **Persona Architecture** — Modular personality system with ResponseType gating
- 🤫 **Silence Override** — "Shut up" command with joke pool and quiet mode
- ⌨️ **Frontend Text Input** — Type messages instead of speaking, with barge-in support
- 🔧 **Configuration** — Session turn limits and default personality now in config.json

---

## What's New

### Persona Module (v1.6.21)

New `personas/` module with pluggable personality transformers:

| Persona | Allowed Response Types |
|---------|------------------------|
| `neutral` | SYSTEM, COMMAND_ACK, CLARIFICATION, ANSWER |
| `tommy_gunn` | COMMAND_ACK, ANSWER |
| `rick` | ANSWER only |
| `claptrap` | COMMAND_ACK, ANSWER |
| `jarvis` | COMMAND_ACK, ANSWER |
| `plain` | All (no transformation) |

System messages and clarifications always stay neutral — no Rick burps during error messages.

### Silence Override (v1.6.23)

Tell ARGO to stop talking:
- "Shut up", "Stop talking", "Enough", "Quiet"

Behavior:
1. One random joke from fixed pool (8 options)
2. Enters quiet mode (TTS disabled, personality=plain)
3. Voice input still processed, just no spoken response

### Frontend Text Input (v1.6.24)

Type messages directly in the UI:
- Single-line input, ENTER to send
- Bypasses STT (confidence=1.0)
- Same pipeline as voice
- **Turn indicator**: `Turn X/Y`
- **Text barge-in**: Sending while speaking interrupts TTS

### Configuration (v1.6.23)

New config.json options:
```json
{
  "session": {
    "turn_limit": 6
  },
  "personality": {
    "default": "tommy_gunn"
  }
}
```

---

## Bug Fixes

### ARGO Identity False Positive (v1.6.20)
- "Tell me about your feet" no longer triggers identity response
- Changed from substring match to word-boundary regex

---

## Improvements

### Conversational Tommy Gunn (v1.6.22)
- Prompt rewritten for natural dialogue
- Removed rigid structure (hook/correction/explanation)
- Now ends with thoughts that invite response

### State Machine Update (v1.6.24)
- LISTENING → THINKING transition now allowed (for text input)
- Skips TRANSCRIBING state when text is typed

---

## Upgrade Notes

**No new dependencies** — existing `pip install -r requirements.txt` is sufficient.

**Config migration** — Add these to config.json if desired:
```json
{
  "session": { "turn_limit": 6 },
  "personality": { "default": "tommy_gunn" }
}
```

---

## Files Changed

- `personas/` — New module (7 persona files)
- `core/pipeline.py` — Persona integration, silence override, turn broadcast
- `core/intent_parser.py` — SILENCE_OVERRIDE intent
- `core/conversation_buffer.py` — Configurable turn limit
- `main.py` — Text input WebSocket handler
- `frontend-2/AppV4.tsx` — Text input UI (gitignored)
- `config.json` — New session/personality sections
- `GETTING_STARTED.md` — Updated with new features

---

*Released: February 4, 2026*
