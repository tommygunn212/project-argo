"""
LOCAL INPUT SHELL (v1.4.4)

A testing interface for the ARGO artifact chain.

NEW IN v1.4.4:
- Humanized read-only Q&A responses (natural tone, no manual voice)
- System prompt enforces conversational style
- Bans corporate/instructional language patterns

NEW IN v1.4.3:
- Read-only Q&A path for questions (no artifacts created)
- Press-to-talk fixed: mousedown/mouseup/mouseleave
- ANSWER panel displays both Q&A responses and execution results

STRICT RULES:
- No frozen layers modified
- No new execution paths
- No background listening
- No shortcuts
- Every action requires explicit confirmation
- Only calls execute_and_confirm() for execution

This shell mirrors the artifact chain:
  Transcription → Intent → Plan → Execution
           ↓
          Q&A (read-only, routing to hal_chat.py)

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

# Add argo root to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from wrapper.transcription import WhisperTranscriber, TranscriptionArtifact
from wrapper.intent import CommandParser, IntentArtifact
from wrapper.executable_intent import ExecutableIntentEngine
from wrapper.execution_engine import ExecutionMode
from wrapper.argo import execute_and_confirm

# Import hal_chat for Q&A routing
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime" / "ollama"))
try:
    import hal_chat
    HAL_AVAILABLE = True
except Exception:
    HAL_AVAILABLE = False
    print("⚠️ WARNING: hal_chat not available. Q&A routing disabled.")

# ============================================================================
# INITIALIZATION
# ============================================================================

app = FastAPI(title="ARGO Input Shell", version="1.4.2")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Engines
transcription_engine = WhisperTranscriber()
intent_engine = CommandParser()
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


def is_question(text: str) -> bool:
    """
    Check if text is a question.
    Detects: explicit ? or question word patterns (what, how, why, is, can, do, etc.)
    Handles Whisper's punctuation quirks.
    """
    text = text.strip().lower()
    
    # Explicit question mark
    if text.endswith("?"):
        return True
    
    # Question word patterns at the start (handles Whisper's missing punctuation)
    question_words = ["what ", "how ", "why ", "when ", "where ", "which ",
                     "who ", "whom ", "is it", "can i", "can you", "could you",
                     "would you", "do you", "did you", "should i", "does it"]
    
    for word in question_words:
        if text.startswith(word):
            return True
    
    return False


def route_to_qa(text: str) -> Optional[str]:
    """
    Route text to Q&A if it's a question and hal_chat is available.
    Returns the answer text or None if not routable.
    Enforces humanized tone (no manual voice, no corporate language).
    """
    if not HAL_AVAILABLE:
        return None
    
    if not is_question(text):
        return None
    
    try:
        log_action("QA_ROUTE", {"text": text})
        
        # System prompt: Calm, confident, lived-experience voice with contained personality
        system_prompt = """You are responding in READ-ONLY mode. No actions will be taken.

VOICE & PERSONALITY:
- Sound like a person who has actually done this many times
- Calm, confident, conversational tone
- Show genuine expertise through details, not enthusiasm
- No performance energy, no "let's go", no hype language
- No mascot voice or YouTube intro energy
- Keep it grounded and useful

CONTENT STRUCTURE:
- One primary method (not multiple paths)
- One sensory cue (visual, sound, texture, timing)
- One practical trick from lived experience
- Clean, direct explanation

EMOJI USAGE (Rare & Contained):
- Maximum 1-2 emojis per response
- Only if it reinforces tone or subject (🔥 for heat, 🍳 for cooking—not 😋 or 🤯)
- Emojis at end or mid-sentence, never every paragraph
- NEVER: emoji clusters, emojis + hype language, emojis + lists + jokes together
- NEVER: emotional emojis (😋, 🤯, 😱, etc.) or emoji narration

OPTIONAL PREFERENCE HOOK:
- One question at the end if relevant
- Examples: "Crispy or chewy?", "Pan or oven?"
- No emoji in the question itself

NEVER:
- Disclaimers, safety lectures, regulatory language
- Corporate, instructional, or teaching-class tone
- Numbered recipe-card steps (unless explicitly asked)
- Apologetic or hedging language
- Recipe-blog filler or over-explanation
- Multi-question endings

QUALITY TEST:
✔️ Pass: Sounds like a person who cooks (calm, specific, knows what works)
❌ Fail: Sounds like a food blogger (flowery, performative, backstory)
❌ Fail: Sounds like a YouTube intro (hype, energy, "buckle up")
❌ Fail: Sounds like a mascot (emojis everywhere, exclamation marks, "let's go")

BE REAL. BE USEFUL. SOUND EXPERIENCED."""
        
        answer = hal_chat.chat(text, context=system_prompt)
        log_action("QA_ANSWER_GENERATED", {"length": len(answer)})
        return answer
    except Exception as e:
        log_action("QA_ERROR", {"error": str(e)})
        return None


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
    
    Input: WebM audio from browser microphone
    Output: Transcript + TranscriptionArtifact
    
    Process: WebM → WAV (explicit conversion) → Whisper
    """
    webm_path = None
    wav_path = None
    
    try:
        log_action("TRANSCRIBE", {"filename": file.filename, "format": "webm"})
        
        # Read audio file
        contents = await file.read()
        if not contents:
            log_action("TRANSCRIBE_ERROR", {"reason": "Empty audio file"})
            raise HTTPException(status_code=400, detail="No audio data received")
        
        # Step 1: Save WebM from browser as temporary file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(contents)
            webm_path = tmp.name
        
        log_action("AUDIO_SAVED", {"format": "webm", "size": len(contents)})
        
        # Step 2: Convert WebM → WAV (explicit parameters)
        wav_path = webm_path.replace(".webm", ".wav")
        
        try:
            from pydub import AudioSegment
            
            # Load WebM
            audio = AudioSegment.from_file(webm_path, format="webm")
            
            # Export as WAV with explicit parameters
            # 16kHz mono, PCM S16LE (standard for Whisper)
            audio_mono = audio.set_channels(1)  # Mono
            audio_16k = audio_mono.set_frame_rate(16000)  # 16kHz
            
            audio_16k.export(wav_path, format="wav")
            
            log_action("AUDIO_CONVERTED", {
                "from": "webm",
                "to": "wav",
                "duration_ms": len(audio),
                "sample_rate": 16000,
                "channels": 1,
            })
        
        except Exception as e:
            log_action("CONVERSION_FAILED", {"error": str(e)})
            raise HTTPException(status_code=400, detail=f"Could not convert audio: {str(e)}")
        
        # Step 3: Validate WAV file BEFORE Whisper
        if not os.path.exists(wav_path):
            log_action("WAV_NOT_CREATED", {})
            raise HTTPException(status_code=500, detail="WAV file creation failed")
        
        wav_size = os.path.getsize(wav_path)
        if wav_size < 1000:  # Less than 1KB is suspicious
            log_action("WAV_TOO_SMALL", {"size": wav_size})
            raise HTTPException(status_code=400, detail="Audio file too small (< 1KB)")
        
        log_action("WAV_VALIDATED", {"size": wav_size})
        
        # Step 4: Call Whisper with validated WAV
        transcript_artifact = transcription_engine.transcribe(audio_path=wav_path)
        
        # Step 5: Check result
        if not transcript_artifact.transcript_text:
            log_action("WHISPER_EMPTY", {
                "status": transcript_artifact.status,
                "error": transcript_artifact.error_detail,
            })
            raise HTTPException(
                status_code=400,
                detail=f"No speech detected: {transcript_artifact.error_detail}"
            )
        
        # Step 6: Success - store in session
        session_state["transcription_id"] = transcript_artifact.id
        session_state["transcript"] = transcript_artifact.transcript_text
        
        text_preview = transcript_artifact.transcript_text[:50]
        if len(transcript_artifact.transcript_text) > 50:
            text_preview += "..."
        
        log_action("TRANSCRIBE_SUCCESS", {
            "transcription_id": transcript_artifact.id,
            "text": text_preview,
            "language": transcript_artifact.language_detected,
            "confidence": f"{transcript_artifact.confidence:.2f}",
        })
        
        return {
            "status": "transcribed",
            "transcription_id": transcript_artifact.id,
            "transcript": transcript_artifact.transcript_text,
            "message": "✓ Transcript ready. Review and confirm or reject.",
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        log_action("TRANSCRIBE_EXCEPTION", {"error": str(e), "type": type(e).__name__})
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    
    finally:
        # Step 7: Clean up both temp files (always)
        for path in [webm_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {path}: {e}")


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
    Confirm transcript → generate intent OR route to Q&A
    
    Transition: Transcription → Intent (if command)
                Transcription → Q&A (if question, read-only)
    """
    if not session_state["transcript"]:
        raise HTTPException(status_code=400, detail="No transcript to confirm")
    
    try:
        log_action("CONFIRM_TRANSCRIPT", {})
        
        transcript = session_state["transcript"]
        
        # Check if this is a question
        if is_question(transcript):
            answer = route_to_qa(transcript)
            if answer:
                log_action("QA_ROUTED", {"question": transcript})
                return {
                    "status": "qa_answered",
                    "is_question": True,
                    "question": transcript,
                    "answer": answer,
                    "answer_text": f"READ-ONLY RESPONSE\n(No actions executed)\n\n{answer}",
                    "message": "✓ Question answered. Review the response below.",
                }
        
        # Not a question, or Q&A unavailable → proceed with intent generation
        # Generate intent from transcript
        intent_dict = intent_engine.parse(
            raw_text=transcript
        )
        
        # Create intent artifact
        intent_artifact = IntentArtifact()
        intent_artifact.source_type = "transcription"
        intent_artifact.source_artifact_id = session_state["transcription_id"]
        intent_artifact.raw_text = transcript
        intent_artifact.parsed_intent = intent_dict
        intent_artifact.status = "proposed"
        
        # Store in session
        session_state["intent_id"] = intent_artifact.id
        session_state["intent_artifact"] = intent_artifact
        
        log_action("INTENT_GENERATED", {
            "intent_id": intent_artifact.id,
            "intent": str(intent_dict),
        })
        
        return {
            "status": "intent_generated",
            "intent_id": intent_artifact.id,
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
            intent_text=session_state["intent_artifact"].raw_text,
            parsed_intent=session_state["intent_artifact"].parsed_intent,
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


@app.post("/api/confirm-plan")
async def confirm_plan():
    """
    Confirm plan → ready for execution
    
    Transition: Plan → Execution (dry-run)
    """
    if not session_state["plan_artifact"]:
        raise HTTPException(status_code=400, detail="No plan to confirm")
    
    try:
        log_action("CONFIRM_PLAN", {})
        
        # Plan is confirmed, ready for execution
        # Frontend will now show the execution panel
        
        return {
            "status": "plan_confirmed",
            "plan_id": session_state["plan_id"],
            "message": "✓ Plan confirmed. Ready for execution.",
        }
    
    except Exception as e:
        log_action("CONFIRM_PLAN_ERROR", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Plan confirmation failed: {str(e)}")


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
    
    Response includes answer_text for UI display (read-only).
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
        
        # Handle gate failure (result is None)
        if result is None:
            answer_text = "⚠️ EXECUTION BLOCKED\n\n"
            answer_text += "Gate 1 failed: No dry-run simulation was provided.\n"
            answer_text += "The safety gates require a successful dry-run before real execution.\n\n"
            answer_text += "This is expected in the Input Shell prototype.\n"
            answer_text += "Full dry-run simulation will be added in v1.4.3."
            
            log_action("EXECUTION_BLOCKED", {
                "reason": "Gate 1: No dry-run report",
            })
            
            return {
                "status": "blocked",
                "result": None,
                "answer_text": answer_text,
                "message": "⚠️ Execution blocked by safety gate.",
            }
        
        # Generate answer text from execution result
        answer_text = f"Execution Status: {result.execution_status.value}\n"
        answer_text += f"Steps Executed: {result.steps_executed}/{result.total_steps}\n"
        if result.errors:
            answer_text += f"\nErrors:\n"
            for error in result.errors:
                answer_text += f"  - {error}\n"
        if result.steps_executed and result.steps_executed > 0:
            answer_text += f"\nSuccessful: {result.steps_succeeded}/{result.steps_executed}\n"
        
        log_action("EXECUTION_COMPLETE", {
            "status": result.execution_status.value,
            "result_id": result.result_id,
        })
        
        return {
            "status": "executed",
            "result": result.to_dict(),
            "answer_text": answer_text,
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


@app.post("/api/qa")
async def answer_question(text: str):
    """
    Read-only Q&A path (v1.4.3)
    
    If text is a question:
    - Does NOT create IntentArtifact
    - Does NOT create Plan
    - Does NOT touch execution
    - Routes to hal_chat for read-only answer
    - Answer appears ONLY in ANSWER panel
    
    Rules:
    - No confirmation required (output only)
    - No artifact advancement
    - No execution risk
    """
    try:
        if not is_question(text):
            return {
                "status": "not_a_question",
                "message": "Text does not end with '?'",
            }
        
        answer = route_to_qa(text)
        
        if answer is None:
            return {
                "status": "qa_unavailable",
                "message": "Q&A service not available. Use commands instead.",
            }
        
        log_action("QA_COMPLETE", {
            "question_length": len(text),
            "answer_length": len(answer),
        })
        
        return {
            "status": "answered",
            "question": text,
            "answer": answer,
            "answer_text": f"READ-ONLY RESPONSE\n(No actions executed)\n\n{answer}",
        }
    
    except Exception as e:
        log_action("QA_ERROR", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Q&A failed: {str(e)}")


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
