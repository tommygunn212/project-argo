from core.pipeline import ArgoPipeline


class DummyAudio:
    def acquire_audio(self, *args, **kwargs):
        return True

    def release_audio(self, *args, **kwargs):
        return True

    def stop_playback(self, *args, **kwargs):
        return True

    def force_release_audio(self, *args, **kwargs):
        return True


def make_pipeline():
    return ArgoPipeline(DummyAudio(), lambda *_args, **_kwargs: None)


def test_loose_action_check_is_advisory_in_personal_mode():
    pipeline = make_pipeline()
    pipeline.runtime_overrides["personal_mode"] = True
    pipeline.runtime_overrides["music_enabled"] = False
    pipeline.runtime_overrides["gate_resource_level"] = 0

    allowed, reason = pipeline._evaluate_gates("music_playback", "music_player", "t1")

    assert allowed is True
    assert reason == ""


def test_strict_action_check_blocks_in_personal_mode():
    pipeline = make_pipeline()
    pipeline.runtime_overrides["personal_mode"] = True
    pipeline.runtime_overrides["music_enabled"] = False
    pipeline.runtime_overrides["gate_resource_level"] = 2

    allowed, reason = pipeline._evaluate_gates("music_playback", "music_player", "t1")

    assert allowed is False
    assert reason == "RESOURCE:strict:music_disabled"
