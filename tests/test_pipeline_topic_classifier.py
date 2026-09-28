import pytest

from core.pipeline_topic_classifier import classify_canonical_topic


@pytest.mark.parametrize(
    ("text", "expected_topic"),
    [
        ("system health", "SYSTEM_HEALTH"),
        ("how full is c drive", "SYSTEM_HEALTH"),
        ("count to ten", "COUNT"),
        ("what are the argo laws", "ARGO_GOVERNANCE"),
        ("pipeline design", "ARCHITECTURE"),
        ("repo stats", "CODEBASE_STATS"),
        ("what can you do", "CAPABILITIES"),
        ("who are you", "ARGO_IDENTITY"),
    ],
)
def test_expected_canonical_topics(text, expected_topic):
    topic, matches = classify_canonical_topic(text)

    assert topic == expected_topic
    assert matches


@pytest.mark.parametrize(
    "text",
    [
        "what is the best cpu to buy",
        "tell me about your feet",
        "hello there",
        "",
        None,
    ],
)
def test_general_conversation_is_not_claimed_as_canonical(text):
    assert classify_canonical_topic(text) == (None, set())


def test_hardware_identity_query_does_not_become_health_status():
    assert classify_canonical_topic("what cpu do i have") == (None, set())
