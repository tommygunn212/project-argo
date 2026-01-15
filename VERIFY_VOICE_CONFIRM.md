# Voice Confirmation Gate Verification

**Status**: Explicit human confirmation implemented as standalone gate  
**Date**: 2026-01-15  
**Purpose**: Pure text gate between voice transcription and action (before any automation exists)

---

## What This Solves

### The Hazard

Without confirmation, the pipeline could:
- Hallucinate intent (whisper misrecognizes "don't open the door" as "open the door")
- Amplify errors (user speaks in hypothetical, code executes as fact)
- Enable accidental execution (user says something in passing, action happens)

Example:
```
User: "I was thinking, what if we deleted all backups?"
Whisper: "delete all backups"
Auto-action: All backups deleted

User: "WAIT, no!"
[too late]
```

### The Solution

**Introduce friction between recognition and action:**

```
Step 1: voice_one_shot.py
  Mic -> WAV -> Whisper -> Text

Step 2: [HUMAN READS AND COPIES TEXT]

Step 3: voice_confirm.py
  [HUMAN PASTES TEXT]
  Confirm? (yes/no)

Step 4: [ONLY IF yes, action proceeds]
```

This friction is **intentional and good**.

---

## Manual Workflow

No integration. No shared state. Human in the middle.

### Example Session

```bash
# Terminal 1: Record and transcribe
$ python voice_one_shot.py

======================================================================
VOICE ONE-SHOT PIPELINE
======================================================================
Mic (3s) -> Whisper -> Text -> Exit

[... recording ...]

======================================================================
TRANSCRIPT
======================================================================
[00:00:00.000 --> 00:00:02.000]   Turn on the lights

[OK] Pipeline executed successfully
======================================================================

# Human reads transcript, copies text
# User copies: "Turn on the lights"

# Terminal 2: Confirm transcription
$ python voice_confirm.py
[paste transcript here]

======================================================================
TRANSCRIPT
======================================================================
Turn on the lights
======================================================================

Proceed? (yes/no): yes
[OK] Confirmed

# Exit code: 0
# Now downstream automation can proceed (if integrated)
```

### Why This Manual Design?

**No shared state between scripts:**
- voice_one_shot.py doesn't call voice_confirm.py
- voice_confirm.py doesn't call voice_one_shot.py
- Human is the only information channel

**Advantages:**
- Can't be silent failure (human must physically type)
- Can't be default approval (must type exactly "yes")
- Can't be replayed (human controls each step)
- Can't be circumvented by code (no auto-retry)

---

## Implementation Details

### voice_confirm.py Design

**Input**:
- Reads from stdin
- Expects multiple lines: [transcript] + [yes|no]
- Treats everything except last line as transcript
- Last line is user response

**Output**:
- Prints transcript clearly in box
- Shows response decision

**Exit Codes**:
- `0` (success): Response was exactly "yes"
- `1` (denied): Response was anything else or missing
- `130` (interrupted): User hit Ctrl+C

**Constraints** (intentional):
- No retries ("try again")
- No defaults (won't assume yes)
- No fuzzy matching (must be exactly "yes")
- No timeout (waits for human)
- No case sensitivity (accepts "YES", "Yes", "yes")
- No logging of text (no record of what was said)

### Failure Modes

**Test 1: Normal Confirmation**
```
Input:  "Turn on the lights\nyes\n"
Output: [TRANSCRIPT box] [OK] Confirmed
Exit:   0
```

**Test 2: Denial**
```
Input:  "Delete all files\nno\n"
Output: [TRANSCRIPT box] [DENIED] Response was 'no'
Exit:   1
```

**Test 3: Empty Input**
```
Input:  ""
Output: [STDERR] [ERROR] No input provided
Exit:   1
```

**Test 4: Random Response**
```
Input:  "Do something\nmaybe\n"
Output: [TRANSCRIPT box] [DENIED] Response was 'maybe'
Exit:   1
```

**Test 5: No Response (transcript only)**
```
Input:  "Do something\n"
Output: [TRANSCRIPT box] [DENIED] No response provided
Exit:   1
```

All tests pass. All failure modes are loud and clear.

---

## What This Does NOT Do

### What's Explicitly Absent

- ❌ No ARGO integration (yet)
- ❌ No background listening
- ❌ No looping/retry
- ❌ No "smart" parsing (must type exactly "yes")
- ❌ No remembering past confirmations
- ❌ No automatic escalation
- ❌ No timeout (will wait forever)
- ❌ No UI polish
- ❌ No logging of user responses
- ❌ No auto-proceed to action

### Why These Are Absent

This is a **safety gate**, not a service. Once integrated with ARGO, it will:
- Accept confirmation, exit with code 0
- ARGO sees exit code 0, proceeds with action
- Human controls the gate, code controls the action
- Separation of concerns: gate ≠ action

If we added:
- Auto-proceed: No human could block bad recognition
- Logging: Creates record of users rejecting commands (no)
- Timeout: Code decides if human is "too slow"
- Retry: Code decides to ask again (not human)

All of these would shift **control from human to code**. This gate's job is opposite: shift control to human.

---

## Why Friction Is Good

### The Argument for Friction

**Friction prevents accidental execution.**

Frictionless example:
```python
# Bad design
transcript = whisper()           # "turn on lights"
if transcript:
    action(transcript)           # Lights on immediately
```

User says "what if we turned on the lights?" → Lights turn on.

**Friction example** (this design):
```
transcript = whisper()           # "what if we turned on the lights"
print(transcript)                # User reads
user_input = confirm()           # User must type "yes"
if user_input == "yes":
    action(transcript)           # Lights on only if user says yes
```

User says "what if..." → sees full transcript → types "no" → nothing happens.

### Cost-Benefit

**Friction cost**: Human must type two commands + paste one line

**Friction benefit**: Prevents:
- Hallucinated intent (whisper errors)
- Hypothetical voice (user speaking casually)
- Ambient listening (mic picking up background)
- Command injection (voice contains special syntax)

**Cost << Benefit** for safety-critical operations.

---

## Readiness for ARGO Integration

This gate is **ready to integrate but not integrated**:

**Current state**: Two standalone scripts, manual flow

**Integration pathway** (NOT YET IMPLEMENTED):

```python
# In ARGO (future, when requested):

def execute_voice_action(audio_file):
    """Example integration (NOT IMPLEMENTED YET)"""
    
    # Step 1: Transcribe
    transcript = voice_one_shot.py(audio_file)
    
    # Step 2: Confirm (this is where voice_confirm.py would gate)
    # Currently manual; could become:
    #   confirmation = subprocess.call(voice_confirm_gate.py, transcript)
    #   if confirmation != 0:
    #       return "Denied by user"
    
    # Step 3: Execute (only if confirmation = 0)
    action(transcript)
```

**We are NOT doing this yet** because:
- First we verify gate works standalone (DONE)
- Then we add ARGO integration (NEXT, IF REQUESTED)
- Then we add background listening (LAST, IF REQUESTED)

---

## Conclusion

**voice_confirm.py is:**
- ✓ A pure text gate (no dependencies)
- ✓ Intentionally friction-full
- ✓ Fail-safe (defaults to denial)
- ✓ Fail-loud (clear messaging)
- ✓ Fail-fast (immediate response)
- ✓ Rejectionist (rejects anything but "yes")

**It prevents:**
- ✓ Hallucinated intent
- ✓ Accidental execution
- ✓ Silent failures
- ✓ Default approval

**It is ready for:**
- ✓ Standalone use (proven)
- ✓ Manual workflow (documented)
- ✓ Future ARGO integration (designed for)

**This is the last human brake before anything dangerous exists.**
