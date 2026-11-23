"""The dashboard's "show me" board: things ARGO puts on screen for Tommy.

Items are images (a data URL or an https URL) or self-contained HTML/SVG that
the dashboard renders in a sandboxed frame with scripts off. The board keeps
the last few so a reload doesn't lose them, and every add is broadcast to the
open dashboard.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import deque

MAX_ITEMS = 12
MAX_IMAGE_BYTES = 8_000_000
MAX_HTML_CHARS = 300_000
_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=\s]+$")
_HTTPS = re.compile(r"^https://[^\s]+$")


class ShowError(ValueError):
    pass


class ShowBoard:
    def __init__(self) -> None:
        self._items: deque[dict] = deque(maxlen=MAX_ITEMS)
        self._lock = threading.Lock()

    def add(self, body: dict, broadcast=None) -> dict:
        kind = str((body or {}).get("kind") or "").lower()
        title = str((body or {}).get("title") or "").strip()[:120] or "Argo"
        caption = str((body or {}).get("caption") or "").strip()[:400]
        item = {"id": uuid.uuid4().hex[:12], "t": time.time(), "kind": kind,
                "title": title, "caption": caption}
        if kind == "image":
            data_url = str(body.get("data_url") or "")
            url = str(body.get("url") or "")
            if data_url:
                if len(data_url) > MAX_IMAGE_BYTES * 4 // 3 + 100 or not _DATA_URL.match(data_url):
                    raise ShowError("image must be a base64 png/jpeg/webp/gif data URL under 8 MB")
                item["src"] = data_url
            elif url:
                if not _HTTPS.match(url) or len(url) > 2000:
                    raise ShowError("image url must be https")
                item["src"] = url
            else:
                raise ShowError("image needs data_url or url")
        elif kind == "html":
            html = str(body.get("html") or "")
            if not html.strip() or len(html) > MAX_HTML_CHARS:
                raise ShowError(f"html must be 1-{MAX_HTML_CHARS} characters")
            item["html"] = html
        else:
            raise ShowError("kind must be 'image' or 'html'")
        with self._lock:
            self._items.append(item)
        if broadcast:
            try:
                broadcast("show", item)
            except Exception:
                pass
        return {"id": item["id"], "kind": kind, "title": title}

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


BOARD = ShowBoard()
