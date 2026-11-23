"""The dashboard 'show me' board and its helpers."""
import base64
import json

import pytest

from core.show_service import MAX_ITEMS, ShowBoard, ShowError

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()


def test_image_and_html_are_stored_and_broadcast():
    board, sent = ShowBoard(), []
    out = board.add({"kind": "image", "title": "Banana", "data_url": PNG}, lambda k, p: sent.append((k, p)))
    board.add({"kind": "html", "title": "Skadis", "html": "<svg/>", "caption": "cup holder"})
    assert out["kind"] == "image" and sent[0][0] == "show" and sent[0][1]["src"] == PNG
    assert [i["title"] for i in board.snapshot()] == ["Banana", "Skadis"]


@pytest.mark.parametrize("body", [
    {"kind": "image", "data_url": "data:text/html;base64,PGI+"},
    {"kind": "image", "data_url": "javascript:alert(1)"},
    {"kind": "image", "url": "http://insecure.example/x.png"},
    {"kind": "image", "url": "https://ok.example/x.png\n<script>"},
    {"kind": "image"},
    {"kind": "html", "html": "   "},
    {"kind": "video", "url": "https://ok.example/x"},
    {},
])
def test_bad_items_are_refused(body):
    with pytest.raises(ShowError):
        ShowBoard().add(body)


def test_keeps_only_the_latest_items_and_clamps_text():
    board = ShowBoard()
    for i in range(MAX_ITEMS + 5):
        board.add({"kind": "html", "title": "t" * 500, "html": f"<p>{i}</p>", "caption": "c" * 900})
    items = board.snapshot()
    assert len(items) == MAX_ITEMS and items[-1]["html"] == f"<p>{MAX_ITEMS + 4}</p>"
    assert len(items[0]["title"]) == 120 and len(items[0]["caption"]) == 400


def test_dashboard_renders_html_sandboxed_without_scripts():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "frontend-v2" / "index.html").read_text(encoding="utf-8")
    assert "frame.setAttribute('sandbox', '')" in page      # no allow-scripts, no same-origin
    assert "case 'show': handleShow(payload)" in page
    assert page.count("textContent = item.title") == 1      # titles never go through innerHTML


def test_helper_posts_with_the_repair_token(monkeypatch, tmp_path):
    import asyncio
    from core.voice import show
    token = tmp_path / "t"; token.write_text("sekrit")
    monkeypatch.setattr(show, "TOKEN_FILE", token)
    seen = {}

    class Resp:
        def read(self): return json.dumps({"title": "Banana"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout):
        seen["token"] = req.headers["X-argo-repair"]; seen["body"] = json.loads(req.data)
        return Resp()

    monkeypatch.setattr(show.urllib.request, "urlopen", fake_urlopen)
    msg = asyncio.run(show.show_image("Banana", png_bytes=b"abc"))
    assert "Banana" in msg and seen["token"] == "sekrit"
    assert seen["body"]["data_url"].startswith("data:image/png;base64,")
