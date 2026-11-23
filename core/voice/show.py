"""Put something on Tommy's dashboard from inside the voice worker.

    from core.voice.show import show_image, show_html

Both are async and return a short status string. They talk to the backend over
its local, token-guarded ``/api/show`` endpoint; nothing here opens a port.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = ROOT / "runtime" / "repair_bridge.token"
TIMEOUT_S = 30


def _post(body: dict) -> dict:
    token = TOKEN_FILE.read_text(encoding="utf-8")
    port = int(os.getenv("ARGO_HTTP_PORT", "8000"))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/show", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Argo-Repair": token})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode())


async def show_image(title: str, *, png_bytes: bytes | None = None, mime: str = "image/png",
                     url: str = "", caption: str = "") -> str:
    """Show an image. Pass raw bytes (any image/* mime) or an https url."""
    body: dict = {"kind": "image", "title": title, "caption": caption}
    if png_bytes:
        body["data_url"] = f"data:{mime};base64," + base64.b64encode(png_bytes).decode()
    else:
        body["url"] = url
    result = await asyncio.to_thread(_post, body)
    return f"Showing '{result.get('title', title)}' on the dashboard."


async def show_html(title: str, html: str, caption: str = "") -> str:
    """Show a self-contained HTML or SVG page (no scripts run in the frame)."""
    result = await asyncio.to_thread(_post, {"kind": "html", "title": title, "html": html,
                                             "caption": caption})
    return f"Showing '{result.get('title', title)}' on the dashboard."
