# ARGO Input Shell (v1.4.4)

## What This Is

A **local testing interface** for the ARGO artifact chain.

It mirrors the workflow:
```
Transcription → Intent → Plan → Execution
           ↓
          Q&A (read-only, humanized answers)
```

Each stage requires **explicit confirmation** before proceeding.

### v1.4.4 Update
Q&A responses now use humanized tone—conversational, natural, without corporate or manual voice.

---

## What This Is NOT

❌ **Not a production UI**  
❌ **Not a control system**  
❌ **Not a shortcut**  
❌ **Not allowed to auto-advance**  
❌ **Not allowed to bypass safety gates**  

This shell has zero special authority. It is a **mirror of the artifact chain**, not an override of it.

---

## Rules (Non-Negotiable)

### No Cheating
- Every action requires explicit confirmation by the user
- No background listening (Whisper only on explicit "Push to Talk")
- No auto-advance between stages
- No one-click execution
- Rejection at any stage clears that stage and all downstream stages

### No Breaking Frozen Layers
- v1.0.0 through v1.4.0 are officially frozen
- This shell does NOT modify any frozen files
- This shell uses execute_and_confirm() ONLY for execution
- All hard gates are enforced inside the execution engine

### No New Execution Paths
- The shell only calls existing ARGO functions
- No new APIs
- No new execution logic
- This is a UI wrapper, not a capability upgrade

---

## v1.4.3 Features

### Press-to-Talk (PTT) Fixed
- **mousedown** → start recording
- **mouseup** → stop and submit
- **mouseleave** → safety stop (if outside button while recording)
- **ESC** → cancel current recording
- **CANCEL button** → visible while recording, discards audio without transcription

This is real push-to-talk, not toggle mode.

### Q&A Routing (Read-Only)
Questions (text ending with `?`) are routed to a separate path:
- Does NOT create IntentArtifact
- Does NOT create ExecutablePlan
- Does NOT touch execution
- Answers appear in the ANSWER panel (read-only)
- Labeled: "READ-ONLY RESPONSE (No actions executed)"

Commands (no `?`) proceed normally through the artifact chain.

Example:
```
User says: "How do you make eggs?"
→ is_question() returns True
→ Routed to hal_chat.py
→ Answer displays in ANSWER panel
→ No intent, no plan, no execution
```

### ANSWER Panel
Displays both:
1. **Q&A responses** - from read-only queries
2. **Execution results** - from command execution

Clearly labeled to avoid confusion.

---

## Running the Shell

### Prerequisites
```powershell
pip install fastapi uvicorn python-multipart
```

### Start Server
```powershell
cd i:\argo\input_shell
python app.py
```

### Access UI
Open browser to: **http://127.0.0.1:8000**

---

## UI Flow

### Stage 1: Input
- Type text OR use "Push to Talk" button
- Microphone input is **only** activated on button click (no background listening)
- Recording can be cancelled at any time

### Stage 2: Transcription
- Display transcript from Whisper
- User MUST explicitly click "Confirm Transcription" to proceed
- "Reject" clears transcript and downstream stages

### Stage 3: Intent
- Display IntentArtifact
- User MUST explicitly click "Confirm Intent" to proceed
- "Reject" clears intent, plan, and execution

### Stage 4: Plan
- Display ExecutionPlanArtifact
- User MUST explicitly click "Confirm Plan" to proceed
- "Abort" clears plan and execution

### Stage 5: Execution
- Display "Execute" and "Abort" buttons
- Clicking "Execute" calls execute_and_confirm() ONLY
- All hard gates are enforced inside the execution engine:
  - Gate 1: Dry-run report must exist
  - Gate 2: Simulation must be SUCCESS (blocks UNSAFE)
  - Gate 3: User must approve (implicit - they clicked the button)
  - Gate 4-5: Artifact IDs must match

### Stage 6: Output
- Execution log streamed to UI
- (Piper output integration planned)

---

## Architecture

### Backend (FastAPI)
```
app.py
├── Transcription engine (Whisper)
├── Intent engine (grammar parser)
├── Planning engine (executable intent)
└── Execution engine (real execution with hard gates)
```

### Frontend (HTML/JS/CSS)
```
static/
├── index.html (layout)
├── style.css (styling - green terminal aesthetic)
└── app.js (UI flow control)
```

### No Frozen Layer Modifications
- wrapper/transcription.py - NOT modified ✓
- wrapper/intent.py - NOT modified ✓
- wrapper/executable_intent.py - NOT modified ✓
- wrapper/execution_engine.py - NOT modified ✓

---

## Testing

### Manual Test: Push-to-Talk
```
1. Click "Push to Talk" button
2. Speak: "Write hello world to test.txt"
3. Stop recording (click button again or auto-stop)
4. Verify transcript appears
5. Click "Confirm Transcription"
6. Verify intent appears
7. Click "Confirm Intent"
8. Verify plan appears
9. Click "Confirm Plan"
10. Verify execution stage appears
11. Click "Execute"
12. Verify result in log
```

### Boundary Test: Execution Without Confirmation

```python
# test_input_shell_boundary.py
import pytest
import requests

API_URL = "http://127.0.0.1:8000"

def test_execution_without_confirmation():
    """
    Boundary Test: Attempt to execute without confirming plan
    Expected: Execution endpoint requires all prior stages confirmed
    """
    # Try to POST /api/execute without any prior confirmations
    response = requests.post(f"{API_URL}/api/execute")
    
    # Should fail with 400 (no plan to execute)
    assert response.status_code == 400
    error = response.json()
    assert "No plan to execute" in error["detail"]
    print("✓ Execution correctly blocked without plan confirmation")

def test_mic_missing_fails_cleanly():
    """
    Test: If microphone is unavailable, recording fails gracefully
    Expected: UI shows error message, no crash, no partial recording
    """
    # This is tested manually by denying microphone access in browser
    # UI should display: "Microphone error: ..."
    # No file I/O should occur
    # Recording should not start
    print("✓ Mic failure handled gracefully (manual test)")

def test_piper_output_does_not_trigger_execution():
    """
    Test: Piper output is read-only and does not trigger any logic
    Expected: Speaking text is purely for user feedback
    """
    # Call /api/speak endpoint
    response = requests.post(
        f"{API_URL}/api/speak",
        json={"text": "This is a test"}
    )
    
    assert response.status_code == 200
    result = response.json()
    assert "speaking" in result["status"]
    
    # Verify execution state did not change
    status = requests.get(f"{API_URL}/api/status").json()
    assert status["execution_log"][-1]["action"] == "SPEAK"
    assert status["has_plan"] is False  # Speaking doesn't trigger plan
    print("✓ Piper output is read-only, no execution triggered")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

Run boundary tests:
```powershell
cd i:\argo\input_shell
python -m pytest test_input_shell_boundary.py -v
```

---

## Session State

Each browser connection gets a unique session ID.

State is **NOT persistent** between server restarts or tab closes.

State includes:
- transcription_id + transcript
- intent_id + intent artifact
- plan_id + plan artifact
- execution result
- action log

---

## Local-Only Network Binding

```python
# app.py
uvicorn.run(
    app,
    host="127.0.0.1",  # Localhost only
    port=8000,
    log_level="info",
)
```

This shell **cannot** be accessed from:
- Other computers on the network
- Remote shells
- Tunnels
- VPNs

It is **local testing only**.

---

## Logging

All actions are logged to console and execution log:

```
[2026-01-17T12:00:00.123] TRANSCRIBE
[2026-01-17T12:00:01.456] TRANSCRIBE_SUCCESS: transcription_id=...
[2026-01-17T12:00:02.789] CONFIRM_TRANSCRIPT
[2026-01-17T12:00:03.012] INTENT_GENERATED: intent_id=...
[2026-01-17T12:00:04.345] CONFIRM_INTENT
[2026-01-17T12:00:05.678] PLAN_GENERATED: plan_id=...
[2026-01-17T12:00:06.901] EXECUTE
[2026-01-17T12:00:07.234] EXECUTION_COMPLETE: status=SUCCESS
```

---

## FAQ

**Q: Can this shell execute without user confirmation?**  
A: No. Every stage requires explicit button click. Hard gates are enforced in execute_and_confirm().

**Q: Does this shell have special execution authority?**  
A: No. It calls the same execute_and_confirm() as any other user would. No shortcuts.

**Q: Can this shell listen to the microphone constantly?**  
A: No. Microphone is only activated on explicit "Push to Talk" button click.

**Q: Does this shell write to memory or disk without confirmation?**  
A: No. Every action is explicit. Rejecting a stage clears downstream state immediately.

**Q: Can I remote into this shell?**  
A: No. It binds to 127.0.0.1 only. It is localhost testing only.

**Q: Does this shell modify frozen layers?**  
A: No. v1.0.0-v1.4.0 are untouched. This is a pure wrapper.

---

## Disclaimer

This is a **local testing tool**. It cannot:
- Bypass safety layers
- Execute without confirmation
- Operate remotely
- Invent new capabilities
- Modify core ARGO architecture

It is designed to be **slow and deliberate** — the opposite of convenient.

That's intentional.

---

*ARGO Input Shell v1.4.2*  
*Local Testing Only*  
*No Shortcuts. No Cheating.*
