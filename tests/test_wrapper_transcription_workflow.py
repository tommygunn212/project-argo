from types import SimpleNamespace
from unittest.mock import Mock

from wrapper.transcription_workflow import (
    TranscriptionWorkflow,
    transcribe_with_confirmation,
)


def _workflow(*, artifact=None, answer="yes", listening=True):
    artifact = artifact or SimpleNamespace(
        id="artifact-1",
        transcript_text="hello world",
        language_detected="en",
        confidence=0.95,
        status="success",
        error_detail=None,
    )
    return TranscriptionWorkflow(
        whisper_available=True,
        state_machine_available=True,
        state_machine=SimpleNamespace(listening_enabled=lambda: listening),
        artifact_factory=lambda: SimpleNamespace(),
        transcribe_audio=Mock(return_value=artifact),
        storage=SimpleNamespace(confirm=Mock(), reject=Mock()),
        read_confirmation=Mock(return_value=answer),
    )


def test_missing_file_short_circuits_before_state_or_whisper():
    workflow = _workflow()

    confirmed, text, artifact = transcribe_with_confirmation(
        workflow, "missing-audio.wav"
    )

    assert confirmed is False
    assert text == ""
    assert artifact.status == "failure"
    assert artifact.confirmation_status == "rejected"
    workflow.transcribe_audio.assert_not_called()


def test_non_listening_state_blocks_transcription(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"placeholder")
    workflow = _workflow(listening=False)

    confirmed, text, artifact = transcribe_with_confirmation(workflow, str(audio))

    assert (confirmed, text, artifact.status) == (False, "", "blocked")
    workflow.transcribe_audio.assert_not_called()


def test_explicit_confirmation_marks_artifact_and_returns_text(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"placeholder")
    workflow = _workflow(answer="yes")

    confirmed, text, artifact = transcribe_with_confirmation(workflow, str(audio))

    assert confirmed is True
    assert text == "hello world"
    workflow.storage.confirm.assert_called_once_with(artifact.id)
    workflow.storage.reject.assert_not_called()


def test_eof_is_a_rejection(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"placeholder")
    workflow = _workflow()
    workflow.read_confirmation.side_effect = EOFError

    confirmed, text, artifact = transcribe_with_confirmation(workflow, str(audio))

    assert confirmed is False
    assert text == ""
    workflow.storage.reject.assert_called_once_with(artifact.id)
