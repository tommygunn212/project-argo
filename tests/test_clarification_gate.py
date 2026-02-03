import numpy as np
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
        self.strict_lab_mode = True

    def transcribe(self, audio_data, interaction_id: str = ""):
        if not self._stt_results:
            self._last_stt_metrics = None
            return ""
        result = self._stt_results.pop(0)
        self._last_stt_metrics = result.get("metrics")
        return result.get("text", "")

    def speak(self, *args, **kwargs):
        return None


def test_low_conf_ambiguous_triggers_clarification(tmp_path):
    """Low-confidence, single-word question triggers clarification."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "Bananas?", "metrics": {"confidence": 0.40}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    assert any("clarif" in msg.lower() for msg in logs), f"Expected clarification prompt, got: {logs}"
    assert pipeline._session_flags.get("clarification_asked") is True


def test_repeated_clarification_not_asked_twice(tmp_path):
    """Clarification asked once, not repeated in same session."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "Bananas?", "metrics": {"confidence": 0.40}},
        {"text": "Bananas?", "metrics": {"confidence": 0.40}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    
    clarify_count_1 = sum(1 for msg in logs if "clarif" in msg.lower())
    logs.clear()
    
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})
    
    clarify_count_2 = sum(1 for msg in logs if "clarif" in msg.lower())
    
    assert clarify_count_1 > 0, "First interaction should have clarification"
    assert clarify_count_2 == 0, "Second interaction should not have clarification (already asked)"


def test_high_conf_question_bypasses_clarification(tmp_path):
    """High-confidence question bypasses clarification gate."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "What is your name?", "metrics": {"confidence": 0.85}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})

    # Should NOT have clarification (high confidence)
    assert not any("clarif" in msg.lower() for msg in logs), f"Should not clarify high-conf question: {logs}"


def test_flag_persists_until_canonical_hit(tmp_path):
    """Clarification flag persists across interactions until canonical match."""
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "How many bananas?", "metrics": {"confidence": 0.40}},
        {"text": "How many apples", "metrics": {"confidence": 0.40}},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    
    assert pipeline._session_flags.get("clarification_asked") is True
    logs.clear()
    
    # Second interaction with same low confidence should NOT ask clarification again
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})
    
    # Should NOT have clarification (flag already set)
    assert not any("clarif" in msg.lower() for msg in logs), f"Should not clarify twice: {logs}"
    assert pipeline._session_flags.get("clarification_asked") is True, "Flag should still be True"
