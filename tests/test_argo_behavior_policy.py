from wrapper import behavior_policy as policy


def test_query_classification_and_behavior_profile_are_deterministic():
    assert policy.classify_query_type("what is gravity") == "factual"
    assert policy.classify_query_type("explain why the sky is blue") == "exploratory"
    assert policy.classify_query_type("write a python script") == "other"

    assert policy.select_behavior_profile("factual", "strong", True) == {
        "verbosity_override": "short",
        "explanation_depth": "minimal",
        "correction_style": "factual",
    }


def test_familiarity_promotes_and_resets_after_violation():
    state = policy.FAMILIARITY_STATE
    original = dict(state)
    try:
        state.update(level="neutral", successful_turns=0, violations_count=0)
        assert policy.update_familiarity(True) == "neutral"
        assert policy.update_familiarity(True) == "neutral"
        assert policy.update_familiarity(True) == "familiar"
        assert policy.update_familiarity(False, "personality_discipline") == "familiar"
        assert state["violations_count"] == 1
    finally:
        state.clear()
        state.update(original)


def test_behavior_validators_keep_their_public_contracts():
    assert policy.validate_scope("Here is the answer.") == (True, "")
    assert policy.validate_human_first_sentence(
        "Here is the answer.",
        is_casual=True,
        primary_frame="human",
    ) == (True, "")
    assert policy.detect_plausible_hallucination(
        "Here is the answer.",
        has_canonical_knowledge=False,
        primary_frame="practical",
    )[0] is True
