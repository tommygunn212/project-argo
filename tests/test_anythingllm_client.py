import json

from core import anythingllm_client as client


class FakeResponse:
    def __init__(self, events):
        self._events = events
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        for event in self._events:
            yield f"data: {json.dumps(event)}"

    def close(self):
        self.closed = True


def _post_returning(monkeypatch, events):
    response = FakeResponse(events)
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        return response

    monkeypatch.setattr(client.requests, "post", fake_post)
    return response, seen


def test_finalized_empty_stream_is_a_failure(monkeypatch):
    response, _ = _post_returning(
        monkeypatch,
        [{"type": "finalizeResponseStream"}],
    )

    result = client.query_workspace("question")

    assert result == {"ok": False, "error": "AnythingLLM finalized an empty answer"}
    assert response.closed is True


def test_workspace_is_encoded_as_one_url_segment(monkeypatch):
    _, seen = _post_returning(
        monkeypatch,
        [
            {"type": "textResponseChunk", "textResponse": "grounded"},
            {"type": "finalizeResponseStream"},
        ],
    )

    result = client.query_workspace("question", workspace="Tommy/Private Notes")

    assert result["ok"] is True
    assert "/Tommy%2FPrivate%20Notes/stream-chat" in seen["url"]


def test_oversized_stream_is_rejected_and_closed(monkeypatch):
    response, _ = _post_returning(
        monkeypatch,
        [
            {"type": "textResponseChunk", "textResponse": "x" * 20_000},
            {"type": "textResponseChunk", "textResponse": "y" * 20_000},
        ],
    )

    result = client.query_workspace("question")

    assert result["ok"] is False
    assert "exceeded" in result["error"]
    assert response.closed is True


def test_non_list_sources_are_ignored(monkeypatch):
    _post_returning(
        monkeypatch,
        [
            {
                "type": "textResponseChunk",
                "textResponse": "answer",
                "sources": {"unexpected": "shape"},
            },
            {"type": "finalizeResponseStream"},
        ],
    )

    result = client.query_workspace("question")

    assert result == {"ok": True, "answer": "answer", "sources": []}
