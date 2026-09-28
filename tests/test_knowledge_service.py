from core import knowledge_service as service


class FakeConfig:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_anythingllm_is_the_only_supported_runtime_provider(monkeypatch):
    called = {}

    def fake_query(message, **kwargs):
        called.update(message=message, **kwargs)
        return {"ok": True, "answer": "grounded", "sources": []}

    monkeypatch.setattr(service.anythingllm_client, "query_workspace", fake_query)
    result = service.query_knowledge(
        "Tommy's history",
        config=FakeConfig({"rag.provider": "anythingllm", "rag.timeout_seconds": 99}),
    )

    assert result["ok"] is True
    assert called["message"] == "Tommy's history"
    assert called["timeout"] == service.MAX_TIMEOUT


def test_old_sqlite_provider_is_rejected_instead_of_silently_used():
    result = service.query_knowledge(
        "question",
        config=FakeConfig({"rag.provider": "sqlite"}),
    )
    assert result["ok"] is False
    assert result["error"] == "unsupported_provider"


def test_prompt_context_keeps_answer_and_bounded_source_labels():
    context = service.format_prompt_context({
        "ok": True,
        "answer": "The answer.",
        "sources": [
            {"title": "About Tommy", "source": "ignored"},
            {"source": "book/chapter-1"},
            {"unexpected": "shape"},
        ],
    })
    assert context == (
        "AnythingLLM knowledge answer:\nThe answer.\n"
        "Sources: About Tommy; book/chapter-1"
    )


def test_failed_result_never_enters_prompt_context():
    assert service.format_prompt_context({"ok": False, "answer": "ignore me"}) == ""
