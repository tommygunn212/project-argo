import wrapper.prompt_composition as composition


class _DriftMonitor:
    def __init__(self, uncertainty=None, corrections=None):
        self.uncertainty = uncertainty
        self.corrections = corrections or {}
        self.preconditions = []

    def check_preconditions_uncertainty(self, **kwargs):
        self.preconditions.append(kwargs)
        return self.uncertainty

    def apply_corrections(self):
        return self.corrections


def _install_policy(monkeypatch, *, context="gui", casual=False, familiarity="new", profile=None, drift=None):
    profile = profile or {
        "verbosity_override": None,
        "explanation_depth": "normal",
        "correction_style": "direct",
    }
    drift = drift or _DriftMonitor()
    seen = {}
    monkeypatch.setattr(composition, "detect_context", lambda: context)
    monkeypatch.setattr(composition, "classify_query_type", lambda text: "factual")
    monkeypatch.setattr(composition, "infer_canonical_knowledge", lambda text: False)

    def select_behavior(query_type, strength, canonical):
        seen["behavior_strength"] = strength
        return profile

    monkeypatch.setattr(composition, "select_behavior_profile", select_behavior)
    monkeypatch.setattr(composition, "is_casual_question", lambda text: casual)

    def select_frame(query_type, strength, is_casual):
        seen["frame_strength"] = strength
        return "human"

    monkeypatch.setattr(composition, "select_primary_frame", select_frame)
    monkeypatch.setattr(composition, "get_familiarity_level", lambda: familiarity)
    monkeypatch.setattr(composition, "build_behavior_instruction", lambda *args: "BEHAVIOR")
    monkeypatch.setattr(composition, "get_drift_monitor", lambda: drift)
    monkeypatch.setattr(composition, "get_persona_text", lambda persona: "PERSONA")
    monkeypatch.setattr(composition, "get_verbosity_text", lambda value: f"VERBOSITY:{value}")
    monkeypatch.setattr(
        composition,
        "get_cli_formatting_suppression",
        lambda value: "CLI" if value == "cli" else "",
    )
    monkeypatch.setattr(
        composition,
        "get_confidence_instruction",
        lambda strength: f"CONFIDENCE:{strength}",
    )
    return profile, drift, seen


def test_prompt_preserves_policy_order(monkeypatch):
    _install_policy(monkeypatch)

    result = composition.compose_prompt(
        user_input="question",
        active_mode="brainstorm",
        persona="neutral",
        classified_verbosity="short",
        context_strength="strong",
        replay_block="User: old\nAssistant: answer\n\n",
        voice_mode=False,
        mode_enforcement="MODE",
    )

    assert result.full_prompt.decode("utf-8").split("\n\n") == [
        "MODE",
        "PERSONA",
        "BEHAVIOR",
        "VERBOSITY:short",
        "CONFIDENCE:strong",
        "User: old\nAssistant: answer",
        "question",
    ]


def test_cli_context_forces_weak_context(monkeypatch):
    _profile, _drift, seen = _install_policy(monkeypatch, context="cli")

    result = composition.compose_prompt(
        user_input="question",
        active_mode=None,
        persona="neutral",
        classified_verbosity="short",
        context_strength="strong",
        replay_block="",
        voice_mode=False,
        mode_enforcement="MODE",
    )

    prompt = result.full_prompt.decode("utf-8")
    assert seen == {"behavior_strength": "weak", "frame_strength": "weak"}
    assert "CLI" in prompt
    assert "CONFIDENCE:weak" in prompt


def test_trusted_casual_constraint_is_first(monkeypatch):
    _install_policy(monkeypatch, casual=True, familiarity="trusted")

    result = composition.compose_prompt(
        user_input="why do people do that",
        active_mode=None,
        persona="neutral",
        classified_verbosity="short",
        context_strength="weak",
        replay_block="",
        voice_mode=False,
        mode_enforcement="MODE",
    )

    assert result.full_prompt.decode("utf-8").startswith(
        composition.TRUSTED_CASUAL_CONSTRAINT
    )


def test_drift_corrections_and_uncertainty_update_prompt_metadata(monkeypatch):
    drift = _DriftMonitor(
        uncertainty={
            "require_phrases": ["I cannot verify"],
            "prohibit_phrases": ["definitely"],
        },
        corrections={
            "force_verbosity": "short",
            "force_explanation_depth": "minimal",
        },
    )
    profile, _, _ = _install_policy(
        monkeypatch,
        profile={
            "verbosity_override": "long",
            "explanation_depth": "normal",
            "correction_style": "direct",
        },
        drift=drift,
    )

    result = composition.compose_prompt(
        user_input="give me a fact",
        active_mode=None,
        persona="neutral",
        classified_verbosity="long",
        context_strength="weak",
        replay_block="",
        voice_mode=False,
        mode_enforcement="MODE",
    )

    prompt = result.full_prompt.decode("utf-8")
    assert result.classified_verbosity == "short"
    assert profile["explanation_depth"] == "minimal"
    assert "Required phrasing: I cannot verify" in prompt
    assert "Prohibited: definitely" in prompt
    assert drift.preconditions[0]["query_demands_certainty"] is True
