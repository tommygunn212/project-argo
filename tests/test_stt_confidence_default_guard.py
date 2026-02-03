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

    def transcribe(self, audio_data, interaction_id: str = ""):
        if not self._stt_results:
            self._last_stt_metrics = None
            return ""
        result = self._stt_results.pop(0)
        self._last_stt_metrics = result.get("metrics")
        return result.get("text", "")

    def speak(self, *args, **kwargs):
        return None


def test_stt_confidence_default_guard(tmp_path):
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    stt_results = [
        {"text": "My name is Tommy", "metrics": {"confidence": 0.1}},
        {"text": "What is my name?", "metrics": None},
    ]
    pipeline = ScriptedPipeline(stt_results, broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {}

    audio = np.zeros(16000, dtype=np.float32)
    pipeline.run_interaction(audio, interaction_id="t1", replay_mode=True, overrides={"suppress_tts": True})
    pipeline.run_interaction(audio, interaction_id="t2", replay_mode=True, overrides={"suppress_tts": True})

    assert pipeline._memory_store.list_memory("FACT") == []
    assert any(msg.startswith("Argo:") for msg in logs)
