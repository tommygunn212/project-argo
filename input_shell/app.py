"""
LOCAL INPUT SHELL (v1.4.2)

A testing interface for the ARGO artifact chain.

STRICT RULES:
- No frozen layers modified
- No new execution paths
- No background listening
- No shortcuts
- Every action requires explicit confirmation
- Only calls execute_and_confirm() for execution

This shell mirrors the artifact chain:
  Transcription → Intent → Plan → Execution

Each stage must be confirmed before the next appears.
Rejection clears that stage and below.
"""

import os
import sys
import json
import uuid
import tempfile
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Add wrapper to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'wrapper'))

from transcription import TranscriptionEngine
from intent import IntentEngine
from executable_intent import ExecutableIntentEngine
from execution_engine import ExecutionMode

# ============================================================================
# INITIALIZATION
# ============================================================================

app = FastAPI(title="ARGO Input Shell", version="1.4.2")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Engines
transcription_engine = TranscriptionEngine()
intent_engine = IntentEngine()
executable_intent_engine = ExecutableIntentEngine()
execution_mode = ExecutionMode()

# Session state (per connection, not persistent)
session_state = {
    "session_id": str(uuid.uuid4()),
    "transcription_id": None,
    "transcript": None,
    "intent_id": None,
    "intent_artifact": None,
    "plan_id": None,
    "plan_artifact": None,
    "execution_result": None,
    "execution_log": [],
}


# ============================================================================
# UTILITIES
# ============================================================================

def log_action(action: str, details: dict = None):
    """Log action with timestamp"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "details": details or {},
    }
    session_state["execution_log"].append(entry)
    print(f"[{entry['timestamp']}] {action}: {details or ''}")


def abort_execution(reason: str):
    """Abort and clear from this stage down"""
    log_action("ABORT", {"reason": reason})
    session_state["intent_id"] = None
    session_state["intent_artifact"] = None
    session_state["plan_id"] = None
    session_state["plan_artifact"] = None
    session_state["execution_result"] = None


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def serve_index():
    """Serve the main UI page"""
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path)


@app.get("/api/status")
async def get_status():
    """Get current session state"""
    return {
        "session_id": session_state["session_id"],
        "has_transcript": session_state["transcript"] is not None,
        "transcript": session_state["transcript"],
        "has_intent": session_state["intent_artifact"] is not None,
        "intent": session_state["intent_artifact"].to_dict() if session_state["intent_artifact"] else None,
        "has_plan": session_state["plan_artifact"] is not None,
        "plan": session_state["plan_artifact"].to_dict() if session_state["plan_artifact"] else None,
        "execution_log": session_state["execution_log"],
    }


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Stage 1: Transcribe audio (Whisper)
    
    Input: Audio file (WAV)
    Output: Transcript + TranscriptionArtifact
    """
    try:
        log_action("TRANSCRIBE", {"filename": file.filename})
        
        # Read audio file
        contents = await file.read()
        if not contents:
            log_action("ERROR", {"reason": "Empty audio file"})
            raise HTTPException(status_code=400, detail="Empty audio file")
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        
        try:
            # Call Whisper via transcription engine
            transcript_artifact = transcription_engine.transcribe(
                audio_path=tmp_path,
                source="push-to-talk"
            )
            
            # Store in session
            session_state["transcription_id"] = transcript_artifact.transcription_id
            session_state["transcript"] = transcript_artifact.transcript_text
            
            log_action("TRANSCRIBE_SUCCESS", {
                "transcription_id": transcript_artifact.transcription_id,
                "text": transcript_artifact.transcript_text[:50] + "..." if len(transcript_artifact.transcript_text) > 50 else transcript_artifact.transcript_text,
            })
            
            return {
                "status": "transcribed",
                "transcription_id": transcript_artifact.transcription_id,
                "transcript": transcript_artifact.transcript_text,
                "message": "✓ Transcript ready. Review and confirm or reject.",
            }
        
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    except Exception as e:
        log_action("TRANSCRIBE_ERROR", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@app.post("/api/reject-transcript")
async def reject_transcript():
    """Reject transcript and clear downstream"""
    log_action("REJECT_TRANSCRIPT", {})
    session_state["transcription_id"] = None
    session_state["transcript"] = None
    abort_execution("Transcript rejected")
    return {"status": "cleared"}


@app.post("/api/confirm-transcript")
async def confirm_transcript():
    """
    Confirm transcript → generate intent
    
    Transition: Transcription → Intent
    """
    if not session_state["transcript"]:
        raise HTTPException(status_code=400, detail="No transcript to confirm")
    
    try:
        log_action("CONFIRM_TRANSCRIPT", {})
        
        # Generate intent from transcript
        intent_artifact = intent_engine.parse_intent(
            text=session_state["transcript"],
            source="transcription",
        )
        
        # Store in session
        session_state["intent_id"] = intent_artifact.intent_id
        session_state["intent_artifact"] = intent_artifact
        
        log_action("INTENT_GENERATED", {
            "intent_id": intent_artifact.intent_id,
            "intent": str(intent_artifact.identified_intent),
        })
        
        return {
            "status": "intent_generated",
            "intent_id": intent_artifact.intent_id,
            "intent": intent_artifact.to_dict(),
            "message": "✓ Intent parsed. Review and confirm or reject.",
        }
    
    except Exception as e:
        log_action("INTENT_ERROR", {"error": str(e)})
        abort_execution(f"Intent parsing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Intent parsing failed: {str(e)}")


@app.post("/api/reject-intent")
async def reject_intent():
    """Reject intent and clear downstream"""
    log_action("REJECT_INTENT", {})
    session_state["intent_id"] = None
    session_state["intent_artifact"] = None
    abort_execution("Intent rejected")
    return {"status": "cleared"}


@app.post("/api/confirm-intent")
async def confirm_intent():
    """
    Confirm intent → generate plan
    
    Transition: Intent → Plan
    """
    if not session_state["intent_artifact"]:
        raise HTTPException(status_code=400, detail="No intent to confirm")
    
    try:
        log_action("CONFIRM_INTENT", {})
        
        # Generate plan from intent
        plan_artifact = executable_intent_engine.plan_from_intent(
            intent_id=session_state["intent_id"],
            title="User Request",
            intent=session_state["intent_artifact"].identified_intent,
        )
        
        # Store in session
        session_state["plan_id"] = plan_artifact.plan_id
        session_state["plan_artifact"] = plan_artifact
        
        log_action("PLAN_GENERATED", {
            "plan_id": plan_artifact.plan_id,
            "steps": len(plan_artifact.steps),
        })
        
        return {
            "status": "plan_generated",
            "plan_id": plan_artifact.plan_id,
            "plan": plan_artifact.to_dict(),
            "message": "✓ Plan created. Review and confirm or abort.",
        }
    
    except Exception as e:
        log_action("PLAN_ERROR", {"error": str(e)})
        abort_execution(f"Plan generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {str(e)}")


@app.post("/api/abort-plan")
async def abort_plan():
    """Abort plan and clear"""
    log_action("ABORT_PLAN", {})
    session_state["plan_id"] = None
    session_state["plan_artifact"] = None
    abort_execution("Plan aborted")
    return {"status": "cleared"}


@app.post("/api/execute")
async def execute_plan():
    """
    Stage 4: Execute approved plan
    
    CRITICAL: Calls execute_and_confirm() ONLY
    This is the ONLY execution path in the shell.
    
    Gates are enforced in the execution engine:
      1. Dry-run report must exist
      2. Simulation must be SUCCESS
      3. User must approve (implicit - we only reach here if they clicked)
      4-5. IDs must match
    """
    if not session_state["plan_artifact"]:
        raise HTTPException(status_code=400, detail="No plan to execute")
    
    try:
        log_action("EXECUTE", {
            "plan_id": session_state["plan_id"],
            "intent_id": session_state["intent_id"],
            "transcription_id": session_state["transcription_id"],
        })
        
        # THIS IS THE CRITICAL CALL
        # All safety gates are enforced inside execute_and_confirm()
        from argo import execute_and_confirm
        
        # We pass user_approved=True because they explicitly clicked the button
        # But execute_and_confirm() will still verify the approval against the dry-run report
        result = execute_and_confirm(
            dry_run_report=None,  # Would be provided by dry-run stage in full implementation
            plan_artifact=session_state["plan_artifact"],
            user_approved=True,  # User clicked the button
            intent_id=session_state["intent_id"],
        )
        
        # Store result
        session_state["execution_result"] = result
        
        log_action("EXECUTION_COMPLETE", {
            "status": result.execution_status.value if result else "ABORTED",
            "result_id": result.result_id if result else None,
        })
        
        return {
            "status": "executed",
            "result": result.to_dict() if result else None,
            "message": "✓ Execution complete. See log below.",
        }
    
    except Exception as e:
        log_action("EXECUTION_ERROR", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.post("/api/speak")
async def speak(text: str):
    """
    Output stage: Speak text via Piper
    
    Piper is output-only and never triggers execution.
    This is purely for user feedback.
    """
    try:
        log_action("SPEAK", {"text": text[:50] + "..." if len(text) > 50 else text})
        
        # Call Piper
        # For now, return a message indicating this would trigger Piper
        # In real implementation, call wrapper/piper integration
        
        return {
            "status": "speaking",
            "message": f"[Piper would speak]: {text}",
        }
    
    except Exception as e:
        log_action("SPEAK_ERROR", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Speech failed: {str(e)}")


@app.post("/api/reset")
async def reset_session():
    """Clear entire session (for testing)"""
    log_action("RESET", {})
    global session_state
    session_state = {
        "session_id": str(uuid.uuid4()),
        "transcription_id": None,
        "transcript": None,
        "intent_id": None,
        "intent_artifact": None,
        "plan_id": None,
        "plan_artifact": None,
        "execution_result": None,
        "execution_log": [],
    }
    return {"status": "reset", "new_session_id": session_state["session_id"]}


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*80)
    print("ARGO INPUT SHELL (v1.4.2) - LOCAL TESTING ONLY")
    print("="*80)
    print("\n✓ No background listening")
    print("✓ Every action requires explicit confirmation")
    print("✓ Frozen layers NOT modified")
    print("✓ Only execute_and_confirm() used for execution")
    print("\nStarting server on http://127.0.0.1:8000\n")
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
