"""Auditable transcription confirmation workflow for the wrapper CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Callable


@dataclass(frozen=True)
class TranscriptionWorkflow:
    whisper_available: bool
    state_machine_available: bool
    state_machine: Any
    artifact_factory: Callable[[], Any] | None
    transcribe_audio: Callable[..., Any] | None
    storage: Any
    read_confirmation: Callable[[], str]


def _failure_artifact(
    workflow: TranscriptionWorkflow,
    audio_path: str,
    status: str,
    reason: str,
) -> Any:
    if workflow.artifact_factory:
        artifact = workflow.artifact_factory()
        artifact.source_audio = audio_path
        artifact.transcript_text = None
        artifact.language_detected = None
        artifact.confidence = 0.0
        artifact.status = status
        artifact.error_detail = reason
        artifact.confirmation_status = "rejected"
        return artifact
    return SimpleNamespace(
        id=None,
        timestamp=None,
        source_audio=audio_path,
        transcript_text=None,
        language_detected=None,
        confidence=0.0,
        status=status,
        error_detail=reason,
        confirmation_status="rejected",
    )


def transcribe_with_confirmation(
    workflow: TranscriptionWorkflow,
    audio_path: str,
    max_duration_seconds: int = 300,
) -> tuple[bool, str, Any]:
    """Transcribe one file and require explicit approval before returning text."""
    if audio_path and not Path(audio_path).exists():
        reason = f"Audio file not found: {audio_path}"
        return False, "", _failure_artifact(
            workflow, audio_path, "failure", reason
        )

    if (
        workflow.state_machine_available
        and workflow.state_machine
        and not workflow.state_machine.listening_enabled()
    ):
        reason = "Microphone input blocked: not in LISTENING state"
        print(f"⚠ {reason}", file=sys.stderr)
        return False, "", _failure_artifact(
            workflow, audio_path, "blocked", reason
        )

    if not workflow.whisper_available or workflow.transcribe_audio is None:
        reason = "Whisper not installed. Run: pip install openai-whisper"
        print(f"⚠ {reason}", file=sys.stderr)
        return False, "", _failure_artifact(
            workflow, audio_path, "failure", reason
        )

    print("\n🎤 Transcribing audio...", file=sys.stderr)
    artifact = workflow.transcribe_audio(
        audio_path, max_duration_seconds=max_duration_seconds
    )
    if artifact.status == "failure":
        print(f"❌ Transcription failed: {artifact.error_detail}", file=sys.stderr)
        return False, "", artifact
    if artifact.status == "partial":
        print(f"⚠ Partial transcription: {artifact.error_detail}", file=sys.stderr)

    print(f"\n{'=' * 70}", file=sys.stderr)
    print("Here's what I heard:", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(f'\n  "{artifact.transcript_text}"', file=sys.stderr)
    print(
        f"\nLanguage: {artifact.language_detected} | "
        f"Confidence: {artifact.confidence:.0%}",
        file=sys.stderr,
    )
    print(f"{'=' * 70}", file=sys.stderr)
    print("\nProceed with this transcript? (yes/no): ", end="", file=sys.stderr)
    sys.stderr.flush()

    try:
        response = workflow.read_confirmation().strip().lower()
    except EOFError:
        response = "no"
    if response in ("yes", "y", "yep", "yeah", "ok", "sure"):
        workflow.storage.confirm(artifact.id)
        print("✅ Confirmed. Processing transcript...\n", file=sys.stderr)
        return True, artifact.transcript_text, artifact

    workflow.storage.reject(artifact.id)
    print("❌ Rejected. Please try again.\n", file=sys.stderr)
    return False, "", artifact
