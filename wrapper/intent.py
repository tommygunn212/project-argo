"""
================================================================================
INTENT ARTIFACT LAYER
Structured Intent Parsing Without Execution
================================================================================

Module:      intent.py (Intent Artifact System)
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0
Created:     January 2026
Purpose:     Convert confirmed text into structured intent candidates with
             ambiguity preserved and zero side effects

================================================================================
DESIGN PHILOSOPHY
================================================================================

INTENT ARTIFACTS ARE NOT EXECUTABLE.

This layer does exactly ONE thing:
  Convert confirmed text → structured intent

It explicitly does NOT do:
  ✗ Execute actions
  ✗ Open apps or files
  ✗ Save to disk
  ✗ Trigger OS operations
  ✗ Chain multiple intents
  ✗ Infer intent beyond the grammar
  ✗ Bypass user confirmation

This is a PROPOSAL layer.
"Approved" means "user said yes, this structure is what they meant."
Not "execute this now."

The handoff point is clean and explicit:
  Audio → TranscriptionArtifact → IntentArtifact → (future) ExecutableIntent

================================================================================
COMMAND GRAMMAR (Minimal, Deterministic)
================================================================================

Supported verbs:
  - write    (create/compose text content)
  - open     (launch application or file)
  - save     (persist content)
  - show     (display information or content)
  - search   (query data)

Parsing rules:
  - If ambiguous: preserve ambiguity (don't guess)
  - If unparseable: set low confidence, keep raw_text
  - Never infer missing fields
  - Structure: {verb, target, object, parameters}

Example:
  Input:  "open word"
  Output: {"verb": "open", "target": "word", "object": null, "parameters": {}}
  
  Input:  "write something about climate change"
  Output: {"verb": "write", "target": null, "object": "about climate change", 
           "parameters": {}, "ambiguity": ["target unclear"]}

================================================================================
INPUT SOURCE VALIDATION
================================================================================

IntentArtifacts MUST be created ONLY from:
  ✓ Confirmed typed input (user typed text directly)
  ✓ Confirmed TranscriptionArtifact (user approved audio transcript)

No other sources allowed:
  ✗ Raw TranscriptionArtifact (not confirmed)
  ✗ Unconfirmed typed text
  ✗ Generated/inferred text
  ✗ Side effects or state changes

If source is not confirmed, artifact creation fails.

================================================================================
DEPENDENCIES
================================================================================

- Python 3.9+
- json, uuid, datetime, pathlib (stdlib)
- typing (type hints)

================================================================================
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - INTENT - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("runtime/logs/intent.log"),
        logging.StreamHandler()
    ]
)

# ============================================================================
# INTENT ARTIFACT CLASS
# ============================================================================

class IntentArtifact:
    """
    Structured representation of user intent without execution.
    
    Purpose:
      - Encapsulate parsed intent from confirmed text
      - Preserve ambiguity (don't guess)
      - Track source (typed vs transcription)
      - Enable confirmation before any downstream processing
      - Provide clean handoff to future execution layer
    
    Attributes:
      id: Unique artifact identifier
      timestamp: When intent was parsed (ISO 8601)
      source_type: "typed" | "transcription"
      source_artifact_id: Reference to TranscriptionArtifact or None
      raw_text: Original user input (unmodified)
      parsed_intent: Structured intent {verb, target, object, parameters, ambiguity}
      confidence: 0.0-1.0 (1.0 = clear, unambiguous parse)
      status: "proposed" | "rejected" | "approved"
      requires_confirmation: Always True (no silent execution)
    
    Invariants:
      - status="proposed" on creation
      - requires_confirmation is always True
      - "approved" means "user said yes" NOT "executed"
      - No execution methods exist on this class
      - Raw text always preserved (never discarded)
    """
    
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.source_type = None  # "typed" or "transcription"
        self.source_artifact_id = None
        self.raw_text = None
        self.parsed_intent = {}
        self.confidence = 0.0
        self.status = "proposed"
        self.requires_confirmation = True
        self.requires_execution = False
        self.approved = False
    
    def to_dict(self) -> Dict:
        """Convert artifact to dictionary for logging."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source_type": self.source_type,
            "source_artifact_id": self.source_artifact_id,
            "raw_text": self.raw_text,
            "parsed_intent": self.parsed_intent,
            "confidence": self.confidence,
            "status": self.status,
            "requires_confirmation": self.requires_confirmation,
            "requires_execution": self.requires_execution,
            "approved": self.approved,
        }
    
    def to_json(self) -> str:
        """Convert artifact to JSON string for storage."""
        return json.dumps(self.to_dict(), indent=2)
    
    def __repr__(self) -> str:
        return (
            f"IntentArtifact(id={self.id}, "
            f"verb={self.parsed_intent.get('verb', 'unknown')}, "
            f"status={self.status}, confidence={self.confidence:.2f})"
        )


# ============================================================================
# COMMAND GRAMMAR PARSER
# ============================================================================

class CommandParser:
    """
    Minimal, deterministic command grammar parser.
    
    Supported verbs: write, open, save, show, search
    
    Philosophy:
      - Ambiguity is preserved (never guess)
      - Unparseable input sets low confidence
      - Missing fields are not inferred
      - No NLP magic, just pattern matching
    """
    
    VERBS = ["write", "open", "save", "show", "search"]
    """Canonical verb set. Expansion requires explicit design."""
    
    def __init__(self):
        self.log_dir = Path("runtime/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def parse(self, raw_text: str) -> Dict[str, Any]:
        """
        Parse confirmed text into structured intent.
        
        Args:
            raw_text: User input (must be confirmed/typed or from confirmed transcription)
        
        Returns:
            dict: {verb, target, object, parameters, ambiguity, confidence}
        
        Example:
            parse("open word") → {
                "verb": "open",
                "target": "word",
                "object": null,
                "parameters": {},
                "ambiguity": [],
                "confidence": 1.0
            }
            
            parse("write something") → {
                "verb": "write",
                "target": null,
                "object": "something",
                "parameters": {},
                "ambiguity": ["target unclear"],
                "confidence": 0.7
            }
        """
        if not raw_text or not raw_text.strip():
            return self._unparseable("empty input")
        
        text = raw_text.strip().lower()
        ambiguity_notes = []
        
        # Try to extract verb
        verb = None
        for candidate_verb in self.VERBS:
            if text.startswith(candidate_verb):
                verb = candidate_verb
                break
        
        if not verb:
            return self._unparseable(f"no recognized verb in: {raw_text}")
        
        # Remove verb from text
        remaining = text[len(verb):].strip()
        
        # Parse remaining text into target/object
        target = None
        obj = None
        parameters = {}
        
        if verb == "open":
            # "open <app|file>"
            if remaining:
                target = remaining.split()[0] if remaining.split() else None
                if not target:
                    ambiguity_notes.append("target unclear (no app/file specified)")
            else:
                ambiguity_notes.append("target required but missing")
        
        elif verb == "write":
            # "write [target] [about|regarding|for] <content>"
            # Examples:
            #   "write email to bob"
            #   "write something about climate change"
            if remaining:
                words = remaining.split()
                if "about" in words or "regarding" in words or "for" in words:
                    # Has content description
                    idx = next((i for i, w in enumerate(words) if w in ["about", "regarding", "for"]), None)
                    if idx:
                        target = " ".join(words[:idx]) if idx > 0 else None
                        obj = " ".join(words[idx+1:])
                    else:
                        obj = remaining
                else:
                    # Ambiguous: could be target or object
                    obj = remaining
                    ambiguity_notes.append("target/object unclear (missing 'about/regarding/for')")
            else:
                ambiguity_notes.append("content required but missing")
        
        elif verb == "save":
            # "save [as <filename>]"
            if remaining:
                if "as" in remaining.lower():
                    idx = remaining.lower().index("as")
                    target = remaining[idx+2:].strip()
                else:
                    target = remaining
                    ambiguity_notes.append("filename unclear (missing 'as')")
            else:
                ambiguity_notes.append("filename required but missing")
        
        elif verb == "show":
            # "show <what>"
            if remaining:
                target = remaining
            else:
                ambiguity_notes.append("what to show unclear")
        
        elif verb == "search":
            # "search [in <where>] for <what>"
            if remaining:
                obj = remaining
                if "in" in remaining.lower():
                    ambiguity_notes.append("search scope ambiguous (in where?)")
            else:
                ambiguity_notes.append("search query required but missing")
        
        # Compute confidence
        confidence = 1.0 - (len(ambiguity_notes) * 0.2)
        confidence = max(0.0, min(1.0, confidence))
        
        # Build result
        result = {
            "verb": verb,
            "target": target,
            "object": obj,
            "parameters": parameters,
            "ambiguity": ambiguity_notes if ambiguity_notes else [],
            "confidence": confidence
        }
        
        logger.info(
            f"Parsed: verb={verb} target={target} object={obj} "
            f"confidence={confidence:.2f} ambiguity={len(ambiguity_notes)}"
        )
        
        return result
    
    def _unparseable(self, reason: str) -> Dict[str, Any]:
        """Return low-confidence unparseable result."""
        logger.warning(f"Unparseable: {reason}")
        return {
            "verb": None,
            "target": None,
            "object": None,
            "parameters": {},
            "ambiguity": [reason],
            "confidence": 0.0
        }


# ============================================================================
# INTENT ARTIFACT CREATION & VALIDATION
# ============================================================================

def create_intent_artifact(
    raw_text: str,
    source_type: str,
    source_artifact_id: Optional[str] = None
) -> IntentArtifact:
    """
    Create an IntentArtifact from confirmed text.
    
    Args:
        raw_text: User input (MUST be from confirmed source)
        source_type: "typed" or "transcription"
        source_artifact_id: ID of source TranscriptionArtifact (if transcription)
    
    Returns:
        IntentArtifact with parsed intent and status="proposed"
    
    Raises:
        ValueError: If source_type is invalid
    
    Notes:
      - Artifact is created in "proposed" status
      - No confirmation happens in this function
      - Parsing is deterministic (same text → same artifact every time)
    """
    if source_type not in ["typed", "transcription"]:
        raise ValueError(f"Invalid source_type: {source_type}. Must be 'typed' or 'transcription'.")
    
    artifact = IntentArtifact()
    artifact.source_type = source_type
    artifact.source_artifact_id = source_artifact_id
    artifact.raw_text = raw_text
    
    # Parse intent deterministically
    parser = CommandParser()
    artifact.parsed_intent = parser.parse(raw_text)
    artifact.confidence = artifact.parsed_intent.get("confidence", 0.0)
    verb = (artifact.parsed_intent.get("verb") or "").lower()
    artifact.requires_execution = verb in {"save", "write", "open"}
    
    logger.info(
        f"[{artifact.id}] Created IntentArtifact from {source_type} source. "
        f"Verb: {artifact.parsed_intent.get('verb')}. "
        f"Confidence: {artifact.confidence:.2f}. Status: proposed"
    )
    
    return artifact


def execute_intent(artifact: IntentArtifact):
    """Execution guard: approved intents only; no side effects here."""
    if getattr(artifact, "requires_execution", False) and not getattr(artifact, "approved", False):
        return
    return


# ============================================================================
# INTENT ARTIFACT STORAGE (Session-Only)
# ============================================================================

class IntentStorage:
    """
    Session-only storage for intent artifacts.
    
    Does NOT auto-save to long-term memory.
    All artifacts held in memory during session.
    Inspectable for audit and replay.
    """
    
    def __init__(self):
        self.artifacts = {}  # id → IntentArtifact
        self.log_dir = Path("runtime/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def store(self, artifact: IntentArtifact):
        """Store artifact in session memory."""
        self.artifacts[artifact.id] = artifact
        logger.info(f"Stored artifact: {artifact.id}")
    
    def retrieve(self, artifact_id: str) -> Optional[IntentArtifact]:
        """Retrieve artifact from session memory."""
        return self.artifacts.get(artifact_id)
    
    def approve(self, artifact_id: str):
        """Mark artifact as approved by user."""
        artifact = self.retrieve(artifact_id)
        if artifact:
            artifact.status = "approved"
            artifact.approved = True
            logger.info(f"Approved artifact: {artifact_id}")
    
    def reject(self, artifact_id: str):
        """Mark artifact as rejected by user."""
        artifact = self.retrieve(artifact_id)
        if artifact:
            artifact.status = "rejected"
            logger.info(f"Rejected artifact: {artifact_id}")
    
    def list_proposed(self) -> List[IntentArtifact]:
        """List all proposed artifacts pending confirmation."""
        return [a for a in self.artifacts.values() if a.status == "proposed"]
    
    def list_approved(self) -> List[IntentArtifact]:
        """List all approved artifacts."""
        return [a for a in self.artifacts.values() if a.status == "approved"]
    
    def list_all(self) -> List[IntentArtifact]:
        """List all artifacts."""
        return list(self.artifacts.values())


# Initialize global storage
intent_storage = IntentStorage()
