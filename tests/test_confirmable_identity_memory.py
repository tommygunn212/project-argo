import numpy as np
from pathlib import Path
from core.pipeline import ArgoPipeline
from core.memory_store import MemoryStore


class DummyAudio:
    def acquire_audio(self, *args, **kwargs):
        return True

    def release_audio(self, *args, **kwargs):
        return True

    def stop_playback(self, *args, **kwargs):
        return True

    def force_release_audio(self, *args, **kwargs):
        return True


class ScriptedPipeline(ArgoPipeline):
    def __init__(self, stt_results, broadcast):
        super().__init__(DummyAudio(), broadcast)
        self._stt_results = list(stt_results)
        self.llm_enabled = False
        self.runtime_overrides["tts_enabled"] = False

    def transcribe(self, audio_data, interaction_id: str = ""):
        if not self._stt_results:
            self._last_stt_metrics = None
            return ""
        result = self._stt_results.pop(0)
        self._last_stt_metrics = result.get("metrics")
        return result.get("text", "")

    def speak(self, *args, **kwargs):
        return None


def test_high_conf_name_statement_triggers_confirmation(tmp_path):
    """High-confidence 'my name is X' triggers confirmation prompt, doesn't write memory yet."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is Tommy", "metrics": {"confidence": 0.85}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Should ask for confirmation
    assert any("do you want me to remember" in msg.lower() for msg in logs), f"Expected confirmation prompt, got: {logs}"
    
    # Memory should NOT be written yet
    assert pipeline._memory_store.list_memory("FACT") == []
    
    # Flag should be set for next interaction
    assert pipeline._session_flags.get("confirm_name") is True


def test_name_confirmation_yes_writes_memory(tmp_path):
    """User says 'yes' to confirmation -> memory written."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is Tommy", "metrics": {"confidence": 0.85}},
        {"text": "yes", "metrics": {"confidence": 0.99}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    
    # First interaction: name statement
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    logs.clear()
    
    # Second interaction: user approves
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})

    # Should confirm write
    assert any("got it" in msg.lower() for msg in logs), f"Expected confirmation response, got: {logs}"
    
    # Memory should now be written
    memory = pipeline._memory_store.list_memory("FACT")
    assert len(memory) == 1
    assert memory[0].value == "Tommy"
    
    # Flag should be cleared
    assert pipeline._session_flags.get("confirm_name") is False


def test_name_confirmation_no_drops_memory(tmp_path):
    """User says 'no' to confirmation -> memory NOT written, flag cleared."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is Tommy", "metrics": {"confidence": 0.85}},
        {"text": "no", "metrics": {"confidence": 0.99}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    
    # First interaction: name statement
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    logs.clear()
    
    # Second interaction: user denies
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})

    # Should acknowledge silently
    assert any("okay" in msg.lower() for msg in logs)
    
    # Memory should NOT be written
    assert pipeline._memory_store.list_memory("FACT") == []
    
    # Flag should be cleared
    assert pipeline._session_flags.get("confirm_name") is False


def test_low_conf_name_statement_still_prompts_confirmation(tmp_path):
    """Low-confidence name statements still prompt for confirmation."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is Tommy", "metrics": {"confidence": 0.35}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Should still ask for confirmation despite low confidence
    assert any("do you want me to remember" in msg.lower() for msg in logs), f"Expected confirmation prompt, got: {logs}"
    
    # Flag should be set awaiting confirmation
    assert pipeline._session_flags.get("confirm_name") is True
    
    # Memory should NOT be written until user confirms
    assert pipeline._memory_store.list_memory("FACT") == []


def test_name_with_special_characters_sanitized(tmp_path):
    """Name with special chars gets title-cased properly."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is jean-pierre", "metrics": {"confidence": 0.85}},
        {"text": "yes", "metrics": {"confidence": 0.99}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    
    # First interaction
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    
    # Second interaction: approve
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})

    # Memory should be written with title-cased name
    memory = pipeline._memory_store.list_memory("FACT")
    assert len(memory) == 1
    assert memory[0].value == "Jean-Pierre"


def test_question_skips_name_gate(tmp_path):
    """Question (not statement) bypasses name confirmation gate entirely."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "What is my name?", "metrics": {"confidence": 0.85}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Should NOT ask for name confirmation
    assert not any("do you want me to remember" in msg.lower() for msg in logs)
    
    # Flag should NOT be set
    assert pipeline._session_flags.get("confirm_name") is not True


def test_low_conf_identity_question_reads_memory(tmp_path):
    """Personal-mode identity questions answer from memory even at low confidence."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "What is my name?", "metrics": {"confidence": 0.19}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._memory_store.add_memory("FACT", "name", "Tommy", source="test")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t_low_conf", replay_mode=True, overrides={"suppress_tts": True})

    assert any("your name is tommy" in msg.lower() for msg in logs), f"Expected identity answer, got: {logs}"
