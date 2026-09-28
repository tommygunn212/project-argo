"""Contract tests for Classic Voice RAG context retrieval."""

from unittest.mock import Mock

import pytest

from core.pipeline import ArgoPipeline


def _pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = Mock()
    pipeline._record_timeline = Mock()
    pipeline.config = {"rag": "config"}
    return pipeline


@pytest.mark.parametrize(
    ("capability", "permission", "module"),
    [(False, True, True), (True, False, True), (True, True, False)],
)
def test_rag_context_stops_at_each_registry_gate(
    monkeypatch, capability, permission, module
):
    pipeline = _pipeline()
    query = Mock()
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: capability)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: permission)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: module)
    monkeypatch.setattr("core.knowledge_service.query_knowledge", query)

    assert pipeline._get_rag_context("debug the server", "turn-1") == ""
    query.assert_not_called()


def test_conversational_turn_skips_rag_and_records_reason(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: True)

    assert pipeline._get_rag_context("tell me a fishing joke", "turn-2") == ""
    pipeline._record_timeline.assert_called_once_with(
        "RAG_SKIPPED_CONVERSATIONAL", stage="rag", interaction_id="turn-2"
    )


def test_rag_sanitizes_query_and_returns_formatted_context(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: True)
    result = {"matches": ["answer"]}
    query = Mock(return_value=result)
    format_context = Mock(return_value="grounded context")
    monkeypatch.setattr("core.knowledge_service.query_knowledge", query)
    monkeypatch.setattr("core.knowledge_service.format_prompt_context", format_context)

    assert pipeline._get_rag_context(
        "Debug!!! ARGO's   server_log?", "turn-3"
    ) == "grounded context"
    query.assert_called_once_with("debug argo s server log", config=pipeline.config)
    format_context.assert_called_once_with(result)
    pipeline._record_timeline.assert_called_once_with(
        "RAG_QUERY_HIT anythingllm", stage="rag", interaction_id="turn-3"
    )


def test_one_token_sanitized_query_never_reaches_knowledge_service(monkeypatch):
    pipeline = _pipeline()
    pipeline._should_use_rag_context = Mock(return_value=True)
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: True)
    query = Mock()
    monkeypatch.setattr("core.knowledge_service.query_knowledge", query)

    assert pipeline._get_rag_context("ARGO!!!", "turn-4") == ""
    query.assert_not_called()


def test_rag_query_failure_is_contained_and_recorded(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: True)
    monkeypatch.setattr(
        "core.knowledge_service.query_knowledge",
        Mock(side_effect=RuntimeError("offline")),
    )

    assert pipeline._get_rag_context("debug ARGO server", "turn-5") == ""
    pipeline._record_timeline.assert_called_once_with(
        "RAG_QUERY_ERROR", stage="rag", interaction_id="turn-5"
    )


def test_empty_rag_result_is_contained_and_recorded(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr("core.pipeline.is_capability_enabled", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_permission_allowed", lambda _key: True)
    monkeypatch.setattr("core.pipeline.is_module_enabled", lambda _key: True)
    monkeypatch.setattr(
        "core.knowledge_service.query_knowledge", Mock(return_value={"error": "empty"})
    )
    monkeypatch.setattr("core.knowledge_service.format_prompt_context", lambda _result: "")

    assert pipeline._get_rag_context("debug ARGO server", "turn-6") == ""
    pipeline._record_timeline.assert_called_once_with(
        "RAG_QUERY_EMPTY", stage="rag", interaction_id="turn-6"
    )
