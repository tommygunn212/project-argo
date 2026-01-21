# GitHub Milestones & Issues Setup for v1.0.0-voice-core

This file contains the data needed to backfill GitHub Milestones and Issues.

**Instructions:** Create these in the GitHub web UI (settings not available via API in this context).

---

## MILESTONES TO CREATE

Create these milestones in GitHub (Settings → Milestones):

### Milestone 1: Phase 7B — State Machine

**Title:** Phase 7B — Deterministic State Machine  
**Description:**

Core state machine implementation with SLEEP/LISTENING/THINKING/SPEAKING states.

- Deterministic transitions (no loops, no undefined paths)
- <50ms state change latency profiled
- SLEEP blocks voice input absolutely
- LISTENING gates PTT and future wake-word
- All transitions guarded and auditable

**Status:** COMPLETED  
**Due Date:** January 15, 2026  

**References:**
- [PHASE_7B_COMPLETE.md](../../PHASE_7B_COMPLETE.md)
- Commit: `phase-7b-state-machine`

---

### Milestone 2: Phase 7B-2 — Integration & Hard STOP

**Title:** Phase 7B-2 — Integration & Hard STOP Interrupt  
**Description:**

STOP interrupt architecture with <50ms latency guarantee.

- STOP preempts all operations (Piper, LLM, state changes)
- Piper process killed immediately (<10ms)
- LLM calls cancelled, context preserved
- Audio buffer cleared
- Latency guarantee <50ms verified

**Status:** COMPLETED  
**Due Date:** January 16, 2026  

**References:**
- [PHASE_7B-2_COMPLETE.md](../../PHASE_7B-2_COMPLETE.md)
- Commit: `phase-7b2-hard-stop`

---

### Milestone 3: Phase 7B-3 — Command Parsing

**Title:** Phase 7B-3 — Command Parsing with Safety Gates  
**Description:**

Command parsing implementation with priority rules and safety gates.

- Explicit command types (STOP, SLEEP, etc.)
- Parser validates syntax before execution
- Priority rules: STOP > SLEEP > PTT > other
- Graceful error handling returns to LISTENING

**Status:** COMPLETED  
**Due Date:** January 16, 2026  

**References:**
- [PHASE_7B-3_COMPLETE.md](../../PHASE_7B-3_COMPLETE.md)
- File: `wrapper/command_parser.py`

---

### Milestone 4: Option B — Confidence Burn-In

**Title:** Option B — Confidence Burn-In Validation  
**Description:**

Comprehensive validation of stateless voice execution.

- 14/14 tests passed (100% success rate)
- Zero anomalies detected
- 95% confidence assessment
- Tier 1 (Fundamental): 5/5 passed
- Tier 3 (Edge Cases): 3/3 passed
- Tier 4 (Streaming): 3/3 passed

**Status:** COMPLETED  
**Due Date:** January 17, 2026  

**References:**
- [OPTION_B_BURNIN_REPORT.md](../../OPTION_B_BURNIN_REPORT.md)
- [OPTION_B_COMPLETION_BRIEF.md](../../OPTION_B_COMPLETION_BRIEF.md)
- [OPTION_B_CHECKLIST.md](../../OPTION_B_CHECKLIST.md)

---

### Milestone 5: Phase 7A-2 — Audio Streaming

**Title:** Phase 7A-2 — Audio Streaming for Fast Time-to-First-Audio  
**Description:**

Incremental Piper TTS streaming for responsive audio playback.

- Time-to-first-audio: 500-900ms (40-360x faster)
- Non-blocking stream architecture
- Buffered playback with 200ms threshold
- STOP authority maintained during streaming (<50ms)
- Profiling enabled (TTFA metrics captured)
- 5 test queries validated

**Status:** COMPLETED  
**Due Date:** January 17, 2026  

**References:**
- [PHASE_7A2_STREAMING_COMPLETE.md](../../PHASE_7A2_STREAMING_COMPLETE.md)
- File: `core/output_sink.py`
- Commits: `phase-7a2-streaming`

---

### Milestone 6: Phase 7A-3a — Wake-Word Detection Design

**Title:** Phase 7A-3a — Wake-Word Detection Design (Paper-Only)  
**Description:**

Comprehensive architecture design for wake-word detection (implementation pending).

**Design Deliverables:**
1. PHASE_7A3_WAKEWORD_DESIGN.md — 11-section architecture
2. WAKEWORD_DECISION_MATRIX.md — 15-table reference
3. PHASE_7A3_GONO_CHECKLIST.md — 14 acceptance criteria

**Status:** COMPLETED  
**Due Date:** January 18, 2026  

**References:**
- [PHASE_7A3_WAKEWORD_DESIGN.md](../../PHASE_7A3_WAKEWORD_DESIGN.md)
- [WAKEWORD_DECISION_MATRIX.md](../../WAKEWORD_DECISION_MATRIX.md)
- [PHASE_7A3_GONO_CHECKLIST.md](../../PHASE_7A3_GONO_CHECKLIST.md)

---

## ISSUES TO CREATE

Create these issues in GitHub (Issues → New Issue):

### Issue 1: Audio Garbling from WAV Output Headers

**Title:** Audio garbling from WAV output headers during long TTS synthesis  
**Type:** Bug (Priority: High)  
**Status:** CLOSED (Fixed in Phase 7A-2)

**Description:**

TTS responses longer than ~10 seconds produced garbled, staticky audio output.

**Root Cause:**

Piper WAV format output includes a duration field in the header. For responses longer than 10 seconds, the WAV header duration is sometimes incorrect, causing audio players to read the wrong number of bytes and produce noise/corruption.

**Solution:**

Switch Piper to `--output-raw` mode (outputs raw PCM without WAV header). Handle byte-to-float normalization in Python instead (divide 16-bit signed audio by 32767.0 to get float32 range -1.0 to 1.0).

**Impact:**

- Perfect audio fidelity for responses of any length
- No corruption or frame skipping
- Sounddevice handles raw PCM correctly

**Testing:**

- Test short response (<5 sec): Works
- Test medium response (5-30 sec): Works, no corruption
- Test long response (>30 sec): Works, no corruption

**Files Changed:**
- `core/output_sink.py` — Piper subprocess initialization

**Commits:**
- Phase 7A-2 & 7A-3a: Audio streaming + wake-word design complete

**Labels:** `bug`, `high-priority`, `audio`, `phase-7a2`

**Linked Milestone:** Phase 7A-2 — Audio Streaming

---

### Issue 2: Environment Variables Not Loading in Subprocess

**Title:** Environment variables lost when subprocess spawned from PowerShell  
**Type:** Bug (Priority: High)  
**Status:** CLOSED (Fixed in Phase 7A-2)

**Description:**

Piper TTS subprocess launched from PowerShell session had no environment variables set (API keys, model paths, configurations).

**Root Cause:**

PowerShell session environment variables are not inherited by Python subprocess unless explicitly passed. Subprocess receives only the env dict provided at creation time.

**Solution:**

- Use Python-dotenv library to load .env file at application startup
- Build explicit environment dict from .env file + system variables
- Pass complete env dict to subprocess.Popen()

**Impact:**

- Configuration persists across subprocess calls
- Works in any shell (PowerShell, cmd, bash)
- Secrets not in code or hardcoded paths

**Testing:**

- Set API keys in .env
- Run subprocess, verify env vars available
- Verify with subprocess logging

**Files Changed:**
- `.env` — Configuration file (git ignored)
- `wrapper/argo.py` — Env loading at startup

**Commits:**
- Phase 7A-2 & 7A-3a: Audio streaming + wake-word design complete

**Labels:** `bug`, `environment`, `configuration`, `phase-7a2`

**Linked Milestone:** Phase 7A-2 — Audio Streaming

---

### Issue 3: Voice Mode Includes Prior Conversation Context

**Title:** Voice mode leaks prior conversation history in LLM context  
**Type:** Security/Privacy (Priority: Critical)  
**Status:** CLOSED (Fixed in Phase 7A / Option B)

**Description:**

Voice mode queries included prior conversation history in the LLM context, potentially leaking sensitive information that should never be heard in ambient settings.

**Root Cause:**

Memory system queries fired even when `voice_mode=True`. Conversation excerpts retrieved from TF-IDF memory were injected into the prompt as context, compromising voice mode privacy guarantees.

**Solution:**

1. Skip memory system entirely when `voice_mode=True` (memory queries not fired)
2. Add system prompt guardrail: `PRIORITY 0: You are in voice mode. Do not reference prior conversations.`
3. Implement priority layer structure: Priority 0 (guardrails) > Priority 1 (task) > Priority 2 (format) > context
4. Ensure PRIORITY 0 dominates all other prompts (even if bugs exist elsewhere)

**Impact:**

- Voice mode is truly stateless (zero history injection)
- Sensitive data cannot leak even with bugs
- Prompt structure is defensible

**Testing:**

- Tier 1 Fundamental Test 1: Stateless execution with prior conversation in system
  - Expected: Response contains zero reference to prior conversation
  - Result: PASSED

- Full Option B burn-in: 14/14 tests passed, zero context bleed

**Files Changed:**
- `wrapper/argo.py` — voice_mode parameter and memory skip logic
- `wrapper/behavior.py` — build_behavior_instruction() with priority guardrails

**Commits:**
- Phase 7A / Option B burn-in validation

**Labels:** `security`, `privacy`, `voice-mode`, `critical`, `option-b`

**Linked Milestone:** Option B — Confidence Burn-In Validation

---

### Issue 4: STOP Command Queued Behind Audio Playback

**Title:** STOP interrupt blocked during TTS audio playback  
**Type:** Bug (Priority: High)  
**Status:** CLOSED (Fixed in Phase 7A-2 streaming)

**Description:**

User pressing STOP or speaking "STOP" during audio playback was queued behind the playback operation. Long audio responses meant users had to wait for the full response before STOP took effect.

**Root Cause:**

Old implementation blocked on Piper process completion. The main thread was blocked waiting for audio playback to finish, so STOP interrupt handler had to queue behind this blocking wait.

**Solution:**

Implement non-blocking streaming architecture (Phase 7A-2):
- Piper synthesis runs in background subprocess
- Frames read incrementally in a background thread
- STOP handler is independent and not blocked by playback
- STOP immediately kills Piper process (<10ms)

**Impact:**

- <50ms STOP latency maintained even during long audio
- User manual override works instantly
- System stays responsive

**Testing:**

- Phase 7B-2: STOP latency tested <50ms
- Phase 7A-2 streaming: STOP latency verified during audio playback
- Test: "STOP" during 30-second response → interrupt <50ms

**Files Changed:**
- `core/output_sink.py` — Streaming implementation

**Commits:**
- Phase 7A-2 & 7A-3a: Audio streaming + wake-word design complete

**Labels:** `bug`, `high-priority`, `interrupt`, `streaming`, `phase-7a2`

**Linked Milestone:** Phase 7A-2 — Audio Streaming

---

### Issue 5: CLI Formatting Violations in Help Output

**Title:** Help output formatting inconsistent and unclear  
**Type:** UX/Bug (Priority: Medium)  
**Status:** CLOSED (Fixed in Phase 7B-3)

**Description:**

Help text (`--help`) output was misaligned, had inconsistent capitalization, and missing descriptions for commands.

**Root Cause:**

Manual string formatting in help generation without consistent template or structure.

**Solution:**

Standardized command help generation with consistent format:
- Aligned descriptions
- Consistent capitalization
- Complete command documentation
- Examples for each command

**Impact:**

- CLI is self-documenting
- New users can understand commands
- Consistent, professional appearance

**Files Changed:**
- `wrapper/command_parser.py` — Help generation

**Commits:**
- Phase 7B-3: Command Parsing

**Labels:** `ux`, `documentation`, `phase-7b3`

**Linked Milestone:** Phase 7B-3 — Command Parsing with Safety Gates

---

### Issue 6: Wake-Word Detection Design Needed

**Title:** Design wake-word detection architecture before implementation  
**Type:** Feature (Priority: Medium)  
**Status:** CLOSED (Design completed in Phase 7A-3a)

**Description:**

Wake-word detection (e.g., "ARGO, turn on the lights") is deferred from v1.0.0 but needs comprehensive architecture design before implementation can begin.

**Solution:**

Created complete design package:
1. PHASE_7A3_WAKEWORD_DESIGN.md — 11-section architecture
   - Activation model (LISTENING state only)
   - PTT coexistence (SPACEBAR pauses wake-word)
   - STOP dominance (<50ms guaranteed)
   - Resource model (<5% idle CPU)
   - False-positive strategy (silent failures)
   - State machine integration (no bypass)
   - All edge cases documented

2. WAKEWORD_DECISION_MATRIX.md — 15-table reference
   - Master trigger-outcome matrix
   - Behavior tables for all states
   - False-positive matrix
   - PTT override precedence
   - STOP dominance matrix
   - State transition guards
   - Edge case resolution
   - Failure mode resolution

3. PHASE_7A3_GONO_CHECKLIST.md — 14 acceptance criteria
   - Architecture verification (no vague language)
   - STOP/SLEEP/PTT guarantees confirmed
   - Resource constraints validated
   - Integration points clear
   - Test plan achievable
   - 6 NO-GO auto-fail conditions

**Status:** Design complete, ready for Phase 7A-3 implementation approval

**Testing:**

- 14 acceptance criteria must be YES before Phase 7A-3 implementation begins
- If any NO-GO condition triggered, design is abandoned

**Files Changed:**
- `PHASE_7A3_WAKEWORD_DESIGN.md` — Created
- `WAKEWORD_DECISION_MATRIX.md` — Created
- `PHASE_7A3_GONO_CHECKLIST.md` — Created

**Commits:**
- Phase 7A-2 & 7A-3a: Audio streaming + wake-word design complete

**Labels:** `feature`, `design`, `phase-7a3`, `deferred`

**Linked Milestone:** Phase 7A-3a — Wake-Word Detection Design

---

## HOW TO CREATE THESE IN GITHUB

### Creating Milestones

1. Go to your repository on GitHub
2. Click **Settings** (repository settings)
3. In left sidebar, click **Milestones** (under "Collaboration")
4. Click **New Milestone**
5. Fill in:
   - **Title:** (from "Milestone X" section above)
   - **Description:** (from "Description" field)
   - **Due Date:** (from "Due Date" field)
6. Click **Create Milestone**

### Creating Issues

1. Go to your repository on GitHub
2. Click **Issues** (top navigation)
3. Click **New Issue**
4. Fill in:
   - **Title:** (from "Title" field in issue section)
   - **Description:** (use the full Description, Root Cause, Solution, Impact text)
   - **Labels:** (from "Labels" field)
   - **Milestone:** (from "Linked Milestone" field)
5. Click **Submit new issue**
6. After creation, click **Close issue** (since these are already fixed)

---

## LINKING ISSUES TO COMMITS (After Creation)

Once issues are created on GitHub, update commit messages to reference them:

```powershell
# Example: Link issue #45 to a commit
git commit --amend -m "Your commit message

Fixes #45"
```

Or you can manually reference them in the GitHub web UI by adding a comment to each issue:

"Fixed in commit [COMMIT_HASH]"

---

## VERIFICATION CHECKLIST

After creating all milestones and issues:

- [ ] 6 milestones created (7B, 7B-2, 7B-3, Option B, 7A-2, 7A-3a)
- [ ] 6 issues created (all marked as CLOSED)
- [ ] All issues linked to appropriate milestones
- [ ] All issues labeled correctly
- [ ] Release notes mention issues/milestones
- [ ] README links to open issues and milestones

---

*Data prepared for v1.0.0-voice-core release*  
*Created: January 18, 2026*
