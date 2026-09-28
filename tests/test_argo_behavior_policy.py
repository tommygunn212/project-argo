from wrapper import argo


def test_query_classification_and_behavior_profile_are_deterministic():
    assert argo.classify_query_type("what is gravity") == "factual"
    assert argo.classify_query_type("explain why the sky is blue") == "exploratory"
    assert argo.classify_query_type("write a python script") == "other"

    assert argo.select_behavior_profile("factual", "strong", True) == {
        "verbosity_override": "short",
        "explanation_depth": "minimal",
        "correction_style": "factual",
    }


def test_familiarity_promotes_and_resets_after_violation():
    state = argo.FAMILIARITY_STATE
    original = dict(state)
    try:
        state.update(level="neutral", successful_turns=0, violations_count=0)
        assert argo.update_familiarity(True) == "neutral"
        assert argo.update_familiarity(True) == "neutral"
        assert argo.update_familiarity(True) == "familiar"
        assert argo.update_familiarity(False, "personality_discipline") == "neutral"
        assert state["violations_count"] == 1
    finally:
        state.clear()
        state.update(original)


def test_behavior_validators_keep_their_public_contracts():
    assert argo.validate_scope("Here is the answer.") == (True, "")
    assert argo.validate_human_first_sentence(
        "Here is the answer.",
        is_casual=True,
        primary_frame="human",
    ) == (True, "")
    assert argo.detect_plausible_hallucination(
        "Here is the answer.",
        has_canonical_knowledge=False,
        primary_frame="practical",
    )[0] is True
