"""
================================================================================
WHISPER TRANSCRIPTION MODULE
Deterministic Audio-to-Text Conversion for ARGO
================================================================================

Module:      transcription.py (Whisper Integration)
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0
Created:     January 2026
Purpose:     Encapsulate Whisper transcription with clear contracts & auditability

================================================================================
DESIGN PHILOSOPHY
================================================================================

WHISPER IS TRANSCRIPTION ONLY.

This module does exactly ONE thing:
  Convert audio → text

It explicitly does NOT do:
  ✗ Detect intent
  ✗ Execute commands
  ✗ Run background listening
  ✗ Retry silently on failure
  ✗ Auto-save to long-term memory
  ✗ Process audio without user confirmation

Every transcription is:
  ✓ Visible to the user
  ✓ Explicitly confirmable
  ✓ Logged with success/failure status
  ✓ Reversible (no blind automation)

================================================================================
INPUT/OUTPUT CONTRACT
================================================================================

INPUT:
  - audio_path: str (path to WAV file)
  - max_duration_seconds: int (enforce audio length limits)
  - sample_rate: int (known sample rate, e.g., 16000 Hz)
  - language: str (hint, e.g., "en" for English)

OUTPUT (TranscriptionArtifact):
  - id: str (unique artifact ID)
  - timestamp: str (ISO 8601 when transcription occurred)
  - source_audio: str (reference to input audio file)
  - transcript_text: str (raw transcription)
  - language_detected: str (detected language)
  - confidence: float (0.0-1.0, proxy for transcript quality)
  - status: str ("success" | "partial" | "failure")
  - error_detail: str (if status != "success", explain why)
  - confirmation_status: str ("pending" | "confirmed" | "rejected")

FAILURE CASES:
  - Audio file not found → return failure artifact
  - Audio exceeds max_duration → return failure artifact
  - Whisper model fails → return failure artifact
  - User rejects transcript → confirmation_status = "rejected"

NO SILENT FAILURES. Every outcome is explicit.

================================================================================
DEPENDENCIES
================================================================================

- Python 3.9+
- whisper (OpenAI Whisper library)
  Install: pip install openai-whisper
- json, uuid, datetime, pathlib (stdlib)

================================================================================
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - WHISPER - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("runtime/audio/logs/transcription.log"),
        logging.StreamHandler()
    ]
)

# ============================================================================
# TRANSCRIPTION ARTIFACT CLASS
# ============================================================================

class TranscriptionArtifact:
    """
    Lightweight object representing a single transcription event.
    
    Purpose:
      - Encapsulate all data about one transcription
      - Enable auditability (log every artifact)
      - Allow user confirmation before downstream processing
      - Temporary storage (not auto-saved to long-term memory)
    
    Attributes:
      id: Unique artifact identifier
      timestamp: When transcription occurred (ISO 8601)
      source_audio: Reference to input audio file
      transcript_text: Raw transcription from Whisper
      language_detected: Detected language code
      confidence: Proxy confidence score (0.0-1.0)
      status: "success" | "partial" | "failure"
      error_detail: Explanation if status != "success"
      confirmation_status: "pending" | "confirmed" | "rejected"
    """
    
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.source_audio = None
        self.transcript_text = None
        self.language_detected = None
        self.confidence = 0.0
        self.status = "pending"  # pending → success/partial/failure
        self.error_detail = None
        self.confirmation_status = "pending"  # pending → confirmed/rejected
    
    def to_dict(self) -> Dict:
        """Convert artifact to dictionary for logging."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source_audio": self.source_audio,
            "transcript_text": self.transcript_text,
            "language_detected": self.language_detected,
            "confidence": self.confidence,
            "status": self.status,
            "error_detail": self.error_detail,
            "confirmation_status": self.confirmation_status
        }
    
    def to_json(self) -> str:
        """Convert artifact to JSON string for storage."""
        return json.dumps(self.to_dict(), indent=2)
    
    def __repr__(self) -> str:
        return f"TranscriptionArtifact(id={self.id}, status={self.status}, confirmation={self.confirmation_status})"


# ============================================================================
# WHISPER TRANSCRIPTION ENGINE
# ============================================================================

class WhisperTranscriber:
    """
    Deterministic Whisper transcription interface.
    
    Encapsulates Whisper model loading, inference, and error handling.
    All failures explicit. All outputs auditable. No silent retries.
    """
    
    def __init__(self, model_name: str = "base", device: str = "cpu"):
        """
        Initialize Whisper transcriber.
        
        Args:
            model_name: Whisper model size ("tiny", "base", "small", "medium", "large")
            device: "cpu" or "cuda"
        """
        self.model_name = model_name
        self.device = device
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load Whisper model into memory."""
        try:
            import whisper
            logger.info(f"Loading Whisper model: {self.model_name} on device: {self.device}")
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"Whisper model loaded successfully")
        except ImportError:
            logger.error("Whisper not installed. Install with: pip install openai-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    
    def transcribe(
        self,
        audio_path: str,
        max_duration_seconds: int = 300,
        language: Optional[str] = None
    ) -> TranscriptionArtifact:
        """
        Transcribe audio file to text.
        
        Args:
            audio_path: Path to WAV file
            max_duration_seconds: Maximum allowed audio duration (default 5 minutes)
            language: Language hint (e.g., "en", "es")
        
        Returns:
            TranscriptionArtifact with full details and status
        """
        artifact = TranscriptionArtifact()
        artifact.source_audio = audio_path
        
        # Validate audio file exists
        audio_file = Path(audio_path)
        if not audio_file.exists():
            artifact.status = "failure"
            artifact.error_detail = f"Audio file not found: {audio_path}"
            logger.warning(f"[{artifact.id}] {artifact.error_detail}")
            return artifact
        
        # Validate file is readable
        if not audio_file.is_file():
            artifact.status = "failure"
            artifact.error_detail = f"Not a file: {audio_path}"
            logger.warning(f"[{artifact.id}] {artifact.error_detail}")
            return artifact
        
        # Validate audio duration (basic check)
        try:
            import wave
            with wave.open(str(audio_file), 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration_seconds = frames / rate
                
                if duration_seconds > max_duration_seconds:
                    artifact.status = "failure"
                    artifact.error_detail = (
                        f"Audio duration {duration_seconds:.1f}s exceeds "
                        f"max {max_duration_seconds}s"
                    )
                    logger.warning(f"[{artifact.id}] {artifact.error_detail}")
                    return artifact
        except Exception as e:
            artifact.status = "failure"
            artifact.error_detail = f"Failed to validate audio duration: {e}"
            logger.error(f"[{artifact.id}] {artifact.error_detail}")
            return artifact
        
        # Run transcription
        try:
            logger.info(f"[{artifact.id}] Transcribing: {audio_path}")
            
            # Whisper inference
            result = self.model.transcribe(
                str(audio_file),
                language=language,
                verbose=False
            )
            
            artifact.transcript_text = result.get("text", "").strip()
            artifact.language_detected = result.get("language", "unknown")
            
            # Confidence proxy: use average probability from segments
            if "segments" in result and result["segments"]:
                probs = [seg.get("no_speech_prob", 0.0) for seg in result["segments"]]
                avg_no_speech_prob = sum(probs) / len(probs) if probs else 0.0
                artifact.confidence = 1.0 - avg_no_speech_prob  # Inverse of no-speech probability
            else:
                artifact.confidence = 0.9  # Default high confidence if no segments
            
            # Determine status
            if artifact.transcript_text:
                artifact.status = "success"
                logger.info(
                    f"[{artifact.id}] Transcription complete. "
                    f"Text: {artifact.transcript_text[:50]}... "
                    f"Language: {artifact.language_detected} "
                    f"Confidence: {artifact.confidence:.2f}"
                )
            else:
                artifact.status = "partial"
                artifact.error_detail = "Whisper returned empty transcript"
                logger.warning(f"[{artifact.id}] Empty transcription result")
            
            # Confirmation remains pending (user must confirm)
            artifact.confirmation_status = "pending"
            
            return artifact
        
        except Exception as e:
            artifact.status = "failure"
            artifact.error_detail = f"Whisper inference failed: {str(e)}"
            logger.error(f"[{artifact.id}] {artifact.error_detail}")
            return artifact


# ============================================================================
# STANDALONE TRANSCRIPTION FUNCTION
# ============================================================================

def transcribe_audio(
    audio_path: str,
    max_duration_seconds: int = 300,
    language: Optional[str] = None,
    model_name: str = "base",
    device: str = "cpu"
) -> TranscriptionArtifact:
    """
    Transcribe audio file without maintaining model state.
    
    Args:
        audio_path: Path to WAV file
        max_duration_seconds: Maximum allowed audio duration
        language: Language hint
        model_name: Whisper model size
        device: "cpu" or "cuda"
    
    Returns:
        TranscriptionArtifact with transcription and status
    """
    transcriber = WhisperTranscriber(model_name=model_name, device=device)
    return transcriber.transcribe(
        audio_path,
        max_duration_seconds=max_duration_seconds,
        language=language
    )


# ============================================================================
# ARTIFACT STORAGE & RETRIEVAL (Temporary, Session-Only)
# ============================================================================

class TranscriptionStorage:
    """
    Lightweight session-only storage for transcription artifacts.
    
    Does NOT auto-save to long-term memory.
    Artifacts are held in memory during session.
    Log files are written to runtime/audio/logs/ for auditability.
    """
    
    def __init__(self):
        self.artifacts = {}  # id → TranscriptionArtifact
        self.log_dir = Path("runtime/audio/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def store(self, artifact: TranscriptionArtifact):
        """Store artifact in session memory."""
        self.artifacts[artifact.id] = artifact
        logger.info(f"Stored artifact: {artifact.id}")
    
    def retrieve(self, artifact_id: str) -> Optional[TranscriptionArtifact]:
        """Retrieve artifact from session memory."""
        return self.artifacts.get(artifact_id)
    
    def confirm(self, artifact_id: str):
        """Mark artifact as confirmed by user."""
        artifact = self.retrieve(artifact_id)
        if artifact:
            artifact.confirmation_status = "confirmed"
            logger.info(f"Confirmed artifact: {artifact_id}")
    
    def reject(self, artifact_id: str):
        """Mark artifact as rejected by user."""
        artifact = self.retrieve(artifact_id)
        if artifact:
            artifact.confirmation_status = "rejected"
            logger.info(f"Rejected artifact: {artifact_id}")
    
    def list_pending(self):
        """List all artifacts pending confirmation."""
        return [
            a for a in self.artifacts.values()
            if a.confirmation_status == "pending"
        ]


# Initialize global storage
transcription_storage = TranscriptionStorage()
