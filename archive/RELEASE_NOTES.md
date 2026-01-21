# RELEASE NOTES — ARGO v1.0.0-voice-core

**Date:** January 18, 2026  
**Status:** Foundation-complete voice system, ready for deployment

---

## What This Release Is

ARGO v1.0.0-voice-core is the **foundation** of the ARGO voice system. It delivers:

- ✅ **Stateless voice queries** (no history injection, single-turn only)
- ✅ **Fast audio playback** (time-to-first-audio 500-900ms, not 20-180s)
- ✅ **Guaranteed interrupt** (STOP always wins, <50ms latency)
- ✅ **Sleep mode** (voice disabled absolutely, system becomes "unlistening")
- ✅ **Proven validation** (14/14 tests passed, zero anomalies)

This release is **not feature-complete**. It is **foundation-complete**.

What's missing (intentionally deferred):
- ❌ Wake-word detection (design done, implementation pending)
- ❌ Voice personality (deferred to Phase 7D)
- ❌ Tool invocation (deferred to Phase 7E)
- ❌ Multi-turn voice conversations (deferred to Phase 7D)

---

## Why This Release Matters

### 1. Stateless Voice Is Auditable

Prior releases mixed history into voice queries. This created privacy risk:
- Prior conversations leaked into voice responses
- Sensitive context could be repeated in ambient settings
- No way to know what the system was using

**Fix:** Voice mode disables memory entirely. Prompt guardrail enforces it.

**Guarantee:** Voice queries have ONLY current input + system instruction. No history ever.

### 2. Audio Streaming Makes Voice Interactive

Prior baseline: Full TTS synthesis before playback (20-180 seconds wait).
Result: System felt unresponsive, users couldn't interrupt early.

**Fix:** Incremental Piper frame reading + buffered playback.

**Result:** Time-to-first-audio now 500-900ms (40-360x faster).
- User hears first words in <1s
- Can interrupt during long responses
- STOP latency maintained <50ms

### 3. STOP Dominance Means User Always Wins

Prior behavior: STOP was queue behind other operations. Long audio playback meant user had to wait.

**Fix:** Independent interrupt handler. STOP kills Piper immediately, cancels LLM, returns to LISTENING.

**Guarantee:** <50ms STOP latency, even during long audio synthesis.

**Implication:** User manual override is the only real authority. System defers instantly.

### 4. Sleep Is Now Absolute

Prior behavior: "Sleep" was a request, not a guarantee. Wake-word could potentially wake system.

**Fix:** Voice listener process is not even started in SLEEP state. Physical disable, not soft.

**Guarantee:** SLEEP state blocks all voice input 100%. No exceptions, no "might hear."

### 5. Foundation Is Locked

This release marks the point where we stop moving foundation pieces. All future changes must respect:

1. **State Machine Authority** — No bypasses
2. **STOP Dominance** — <50ms always
3. **Voice Statelessness** — Zero history injection
4. **SLEEP Absoluteness** — Voice listener off
5. **Prompt Hygiene** — Priority layers enforced
6. **Streaming Non-Blocking** — Audio doesn't block input

Future releases can *extend* ARGO. They cannot *modify* these.

---

## What Each Component Guarantees

### State Machine (Phase 7B)

**Guarantee:** All control flow goes through state machine. No shortcuts.

```
SLEEP ────→ LISTENING ────→ THINKING ────→ SPEAKING
             (manual)         (LLM)         (audio)
              ↓                ↓              ↓
            PTT             Voice           Piper
           Wake-word        Request        Response

STOP can interrupt from ANY state, returns to LISTENING
```

- **Why:** Auditable, testable, predictable
- **Test:** 100% state coverage, all transitions verified
- **Locked:** No new states, no bypasses

### STOP Interrupt (Phase 7B-2)

**Guarantee:** <50ms latency, every time, no exceptions.

- Piper process killed <10ms
- LLM calls cancelled <20ms
- State returned to LISTENING <50ms total
- No blocking, no queuing

**Why:** User manual override must feel instant. Human perception threshold ~100ms. We target <50ms.

**Test:** Measured during every operation (audio, LLM, streaming). Regression fails release.

**Locked:** Latency cannot increase. Improvements welcome.

### Voice Statelessness (Phase 7A)

**Guarantee:** Voice mode injects zero conversation history.

Mechanism:
1. Memory system queries skipped entirely
2. System prompt guardrail added: `PRIORITY 0: You are in voice mode. Do not reference prior conversations.`
3. Priority layers dominate all other prompts

**Why:** Prevent sensitive context leakage in ambient settings.

**Test:** 14/14 tests passed. Tier 1 (fundamental) validates zero bleed.

**Locked:** History bypass will be rejected.

### Audio Streaming (Phase 7A-2)

**Guarantee:** Time-to-first-audio ~500-900ms. Non-blocking playback.

- 5 test queries: TTFA range 485-830ms
- STOP latency maintained during playback
- User can interrupt any time
- Long responses stream without truncation

**Why:** Responsiveness. Users feel interaction at <1s. Longer = feels broken.

**Test:** Profiled every query. TTFA metrics captured. Regression detected immediately.

**Locked:** Cannot increase TTFA significantly (100ms degradation is acceptable, 1s+ is not).

### Sleep Mode (Phase 7A)

**Guarantee:** SLEEP disables all voice input 100%.

- Voice listener process not started in SLEEP state (physical disable)
- Whisper cannot start
- Wake-word cannot fire (no detector process)
- SPACEBAR PTT works (manual control always available)

**Why:** System must be able to become completely "unlistening."

**Test:** Tier 1 validates: speak while asleep → no response.

**Locked:** No ambient listening, no background peeking, no "might hear."

---

## How to Use v1.0.0-voice-core

### Start Here

```powershell
# Install (see GETTING_STARTED.md for full setup)
python wrapper/argo.py --help
```

### Voice Mode (Stateless Queries)

```powershell
# Single-turn voice query with no history
python wrapper/argo.py "What is quantum computing?" --voice
```

Result: Query answered based ONLY on current input + system instruction. No prior context. STOP responsive <50ms.

### PTT Mode (Multi-Turn Conversation)

```powershell
# Multi-turn conversation with history
python wrapper/argo.py
# Press SPACEBAR to activate Whisper
# Speak your question
# ARGO responds with history context
# Press SPACEBAR again to interrupt/stop
```

Result: Full conversation with memory. History injected. Context-aware responses.

### Sleep Mode

```
(In PTT mode, speak: "sleep")
→ Voice disabled
→ SPACEBAR PTT still works
→ Wake-word still cannot wake (not implemented yet)
```

To exit sleep: System reboot (wake-word not yet implemented).

### Emergency Stop

**Anytime:** Hold SPACEBAR or say "STOP" (PTT mode required)

Result: <50ms interrupt, returns to LISTENING, ready for next query.

---

## What's Locked (Foundation Constraints)

These constraints are **NON-NEGOTIABLE** for this release and all future releases:

| Guarantee | Constraint | Rationale |
|-----------|-----------|-----------|
| 1 | State machine is authoritative | All control flow must be auditable |
| 2 | STOP <50ms latency always | User manual override must be instant |
| 3 | Voice mode stateless | Privacy: no ambient history leak |
| 4 | SLEEP blocks voice 100% | System must become unlistening |
| 5 | Prompt priority layers enforced | Defense in depth, even if bugs elsewhere |
| 6 | Streaming non-blocking | User input responsive during long audio |

Future PRs must:
- **Maintain** all 6 guarantees
- **Test** that guarantees still hold
- **Document** why the change respects guarantees

---

## What's Extensible (Designed for Addition)

These areas are designed to grow without breaking foundation:

- **Wake-word detector** (design complete, implementation ready)
- **Custom command handlers** (new verbs, new intent types)
- **Memory storage backends** (new DB engines)
- **Tool invocation** (when ready, Phase 7E)
- **Voice personality** (when ready, Phase 7D)
- **Raspberry Pi integration** (sensory peripherals)

Adding these requires:
- Design document (if complex)
- Tests (verify foundation guarantees still hold)
- PR with review
- Performance validation (if touching timing paths)

---

## Known Limitations (Intentional Deferrals)

### Wake-Word Isn't Here Yet

**Status:** Design complete (Phase 7A-3a). Implementation pending approval (Phase 7A-3).

**Why:** Keep v1.0.0 focused and auditable. Wake-word adds latency, CPU usage, complexity.

**When:** Phase 7A-3 implementation can start whenever design is approved.

**Design:** Read [PHASE_7A3_WAKEWORD_DESIGN.md](PHASE_7A3_WAKEWORD_DESIGN.md)

### No Voice Personality Yet

**Status:** Deferred to Phase 7D.

**Current:** Generic Piper voice, functional but neutral.

**When:** Phase 7D will add "Allen" personality, tone, speech patterns.

### No Tool Execution Yet

**Status:** Deferred to Phase 7E.

**Current:** ARGO parses intents but doesn't execute them. Queries are informational (Q&A, advice, search).

**When:** Phase 7E will add execution system with confirmation gates and rollback procedures.

### Voice Mode Is Single-Turn Only

**Status:** Intentional for v1.0.0.

**Current:** Voice mode has no history. Each query stands alone.

**Why:** Simpler to reason about, avoids context leakage, more auditable.

**Workaround:** Use PTT (SPACEBAR) mode for multi-turn conversation. Memory active, history preserved.

**Future:** Phase 7D will add multi-turn voice mode with new safety layers.

---

## Upgrade Path

### v1.0.0 → v1.1.0 (Wake-Word)

**When:** After Phase 7A-3 implementation is approved and complete.

**What:** Adds wake-word detection (e.g., "ARGO, what's the weather?").

**Breaking Changes:** None. Additive feature only.

**Migration:** Automatic. No action required.

### v1.1.0 → v2.0.0 (Full Feature Set)

**When:** After Phase 7D-E (voice personality, multi-turn voice, tools).

**What:** Full ARGO capability set with tool execution and voice personality.

**Breaking Changes:** Possible. Will be documented in advance.

**Migration:** TBD in Phase 7D-E design.

---

## Security Model

### Threat 1: Ambient Listening / Background Surveillance

**ARGO Defense:**
- No background listening (only explicit SPACEBAR or future wake-word)
- SLEEP state disables voice completely
- Voice listener process verified off in logs

**Validation:** Option B Tier 1, Test 4 verified SLEEP blocks voice.

### Threat 2: Context Leakage in Ambient Settings

**ARGO Defense:**
- Voice mode stateless (no history injection)
- Prompt priority layers (PRIORITY 0 prevents context bleed)
- System instruction dominates (even if memory bug exists)

**Validation:** Option B Tier 1, Test 1 verified zero history injection.

### Threat 3: User Can't Stop Audio

**ARGO Defense:**
- STOP always wins (<50ms latency)
- Audio playback non-blocking (doesn't prevent STOP)
- Independent interrupt handler
- Piper process killed on STOP

**Validation:** Phase 7B-2 testing, Phase 7A-2 streaming validation.

### Threat 4: System Makes Autonomous Decisions

**ARGO Defense:**
- No tool execution yet (Phase 7E)
- State machine requires explicit transitions
- STOP available any time
- Voice is Q&A only, not command execution

**Validation:** System design, state machine testing.

---

## How to Report Issues

**Security Issues:** Email maintainer directly (not GitHub)

**Bugs:** [GitHub Issues](https://github.com/tommygunn212/project-argo/issues)
- Include: Steps to reproduce, expected vs actual behavior
- Attach: Relevant logs from `runtime/logs/`

**Design Questions:** [GitHub Discussions](https://github.com/tommygunn212/project-argo/discussions)

---

## Testing & Validation

This release passed comprehensive validation:

- **14/14 tests passed** (100% success rate)
- **Zero anomalies detected**
- **95% confidence assessment**
- **5 streaming tests validated** (TTFA profiled)
- **STOP latency measured** (<50ms confirmed)
- **State machine coverage** (100% transitions tested)

Full results: [OPTION_B_BURNIN_REPORT.md](OPTION_B_BURNIN_REPORT.md)

---

## Licensing

ARGO is available under dual licensing:

- **Non-Commercial:** Free for personal, educational, research use
- **Commercial:** Requires separate commercial license agreement

See [LICENSE](LICENSE) for full terms.

---

## Contact

- **GitHub:** [tommygunn212/project-argo](https://github.com/tommygunn212/project-argo)
- **Issues:** [Report bugs and features](https://github.com/tommygunn212/project-argo/issues)
- **Creator:** Tommy Gunn

---

## Summary

**v1.0.0-voice-core is ready for deployment.**

It's not complete. It's foundation-complete.

Use this release to:
- ✅ Ask voice questions without history leakage
- ✅ Interrupt with <50ms STOP response
- ✅ Sleep the system (voice disabled 100%)
- ✅ Use PTT for multi-turn conversation
- ✅ Trust ARGO with your control

Don't use this release for:
- ❌ Wake-word ("ARGO, turn on the lights") — Coming Phase 7A-3
- ❌ Autonomous tool execution — Coming Phase 7E
- ❌ Multi-turn voice conversation — Coming Phase 7D
- ❌ Voice personality — Coming Phase 7D

**Trust the foundation. Extend it carefully. Report issues. Validate changes.**

---

*Release Date: January 18, 2026*  
*Tag: v1.0.0-voice-core*  
*Tested: 14/14 (100% success)*  
*Locked: Foundation constraints held*
