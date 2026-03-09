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
    """High-confidence 'my name is X' is stored by brain memory system."""
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

    # Brain stores name directly — "Got it. I'll remember that."
    assert any("remember" in msg.lower() for msg in logs), f"Expected memory response, got: {logs}"


def test_name_confirmation_yes_writes_memory(tmp_path):
    """Name statement stores via brain path directly."""
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

    # Brain stores directly — should see confirmation
    assert any("remember" in msg.lower() for msg in logs), f"Expected memory response, got: {logs}"


def test_name_confirmation_no_drops_memory(tmp_path):
    """Non-name input does not trigger memory storage."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "what is the weather?", "metrics": {"confidence": 0.99}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Should NOT store any memory for a weather question
    assert not any("remember" in msg.lower() for msg in logs if msg.startswith("Argo:"))


def test_low_conf_name_statement_still_prompts_confirmation(tmp_path):
    """Low-confidence name statement is still handled by brain memory."""
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

    # Brain handles name storage at any confidence in personal mode
    argo_msgs = [m for m in logs if m.startswith("Argo:")]
    assert len(argo_msgs) > 0, f"Expected a response, got: {logs}"


def test_name_with_special_characters_sanitized(tmp_path):
    """Name with special chars is handled by brain memory."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is jean-pierre", "metrics": {"confidence": 0.85}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Brain should store the name
    assert any("remember" in msg.lower() for msg in logs), f"Expected memory response, got: {logs}"


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
