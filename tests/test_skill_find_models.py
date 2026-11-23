import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx

from argo_skills import find_models as skill

ASYNC_CLIENT = httpx.AsyncClient


def run_search(monkeypatch, handler, query="egg cup", show=None):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(skill.httpx, "AsyncClient", lambda **kwargs: ASYNC_CLIENT(transport=transport, **kwargs))
    saved = MagicMock()
    monkeypatch.setattr(skill, "RESULTS_FILE", saved)
    viewer = show or AsyncMock(return_value="shown")
    monkeypatch.setattr(skill, "show_html", viewer)
    answer = asyncio.run(skill.find_models(query))
    return answer, saved, viewer


def test_printables_cards_order_and_saved_results(monkeypatch):
    def handler(request):
        assert request.url.host == "api.printables.com"
        payload = json.loads(request.content)
        assert payload["variables"]["query"] == "egg cup"
        assert "searchPrints2" in payload["query"]
        return httpx.Response(200, json={"data": {"searchPrints2": {"items": [
            {"id": str(i), "name": name, "user": {"publicUsername": "Chef"},
             "images": [{"filePath": f"models/{i}.png"}]}
            for i, name in enumerate(["Cup <one>", "Cup two", "Cup three"], 1)
        ]}}})

    answer, saved, viewer = run_search(monkeypatch, handler)
    assert answer.index("1. Cup <one>") < answer.index("2. Cup two") < answer.index("3. Cup three")
    cards = viewer.await_args.args[1]
    assert "Cup &lt;one&gt;" in cards and "https://media.printables.com/models/1.png" in cards
    assert "By Chef" in cards and "https://www.printables.com/model/1" in cards
    assert json.loads(saved.write_text.call_args.args[0]) == [
        {"id": str(i), "url": f"https://www.printables.com/model/{i}"} for i in range(1, 4)
    ]


def test_makerworld_fills_remaining_slots_and_blocks_are_quiet(monkeypatch):
    def handler(request):
        if request.url.host == "api.printables.com":
            return httpx.Response(200, json={"data": {"searchPrints2": {"items": [
                {"id": "7", "name": "First", "user": {}, "images": []}
            ]}}})
        assert request.url.params["keyword"] == "egg cup"
        return httpx.Response(200, json={"hits": [{"id": 8, "title": "Second", "designCreator": {"name": "Maker"}, "cover": "https://example.com/8.png"}]})

    answer, saved, viewer = run_search(monkeypatch, handler)
    assert "1. First" in answer and "2. Second, by Maker" in answer
    assert json.loads(saved.write_text.call_args.args[0])[1]["url"] == "https://makerworld.com/en/models/8"
    assert "https://example.com/8.png" in viewer.await_args.args[1]

    def blocked(request):
        return handler(request) if request.url.host == "api.printables.com" else httpx.Response(403)

    answer, _, _ = run_search(monkeypatch, blocked)
    assert "1. First" in answer and "MakerWorld" not in answer


def test_search_failure_clears_old_results_and_does_not_show(monkeypatch):
    answer, saved, viewer = run_search(monkeypatch, lambda request: httpx.Response(503))
    assert "couldn't reach" in answer
    assert json.loads(saved.write_text.call_args.args[0]) == []
    viewer.assert_not_awaited()


def test_empty_query_and_dashboard_failure(monkeypatch):
    answer, saved, viewer = run_search(monkeypatch, lambda request: (_ for _ in ()).throw(AssertionError("network used")), "  ")
    assert "What kind" in answer
    saved.write_text.assert_not_called()
    viewer.assert_not_awaited()

    def handler(request):
        if request.url.host == "api.printables.com":
            return httpx.Response(200, json={"data": {"searchPrints2": {"items": [{"id": 1, "name": "Cup"}]}}})
        return httpx.Response(403)

    answer, _, _ = run_search(monkeypatch, handler, show=AsyncMock(side_effect=OSError("offline")))
    assert "1. Cup" in answer and "couldn't show" in answer


def test_tool_contract():
    assert skill.TOOLS == [skill.find_models]
    assert asyncio.iscoroutinefunction(skill.find_models)
    assert skill.find_models.__doc__ and skill.find_models.__annotations__["query"] == "str"
