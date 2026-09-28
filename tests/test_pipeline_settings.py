from core.pipeline_settings import PipelineSettings, load_pipeline_settings


class Config:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        value = self.values.get(key, default)
        if isinstance(value, Exception):
            raise value
        return value


def test_defaults_are_valid_without_optional_config():
    assert load_pipeline_settings(None, {}) == PipelineSettings()


def test_thresholds_and_lengths_are_clamped():
    settings = load_pipeline_settings(
        Config(
            {
                "guards.tts.min_text_length": 0,
                "guards.tts.min_confidence": 4.0,
                "guards.stt.personal_min_text_length": -8,
                "guards.stt.personal_min_confidence": -2.0,
                "speech_to_text.min_duration_seconds": 0.1,
                "audio.vad_silence_pad_ms": 450,
            }
        ),
        {},
    )

    assert settings.tts_min_text_length == 1
    assert settings.tts_min_confidence == 1.0
    assert settings.personal_mode_min_text_length == 1
    assert settings.personal_mode_min_confidence == 0.0
    assert settings.stt_min_duration_seconds == 0.45


def test_runtime_strict_mode_overrides_persisted_config():
    settings = load_pipeline_settings(
        Config({"modes.strict_lab_mode": True}),
        {"strict_lab_mode": False},
    )

    assert settings.strict_lab_mode is False


def test_late_config_error_preserves_values_loaded_before_it():
    settings = load_pipeline_settings(
        Config(
            {
                "conversation.buffer_size": 40,
                "conversation.ledger_size": 12,
                "speech_to_text.min_rms_threshold": ValueError("bad value"),
            }
        ),
        {},
    )

    assert settings.conversation_buffer_size == 40
    assert settings.conversation_ledger_size == 12
    assert settings.stt_min_rms_threshold == PipelineSettings().stt_min_rms_threshold
