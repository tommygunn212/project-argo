"""H2D print requests: ask first, then (once the printer is set up) send.

Tommy's rule: she never starts a print on her own. A print goes through two
steps: ``request_print`` writes down exactly what would be printed (model,
quantity, material, colour) and ``confirm_print`` runs only after he says yes
to that request. Until the printer's address, serial and LAN access code are
configured, a confirmed request is saved and waits; nothing is sent.

Printer settings live in config.json under "printer": {"ip", "serial"}. The
access code is a secret and is read only from the ARGO_H2D_ACCESS_CODE
environment variable, never from a file in the repo and never logged.

Status: the request/confirm flow is tested. Sending to the real printer and
reading its live status are NOT proven - they need Tommy's printer details.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
REQUESTS_FILE = ROOT / "runtime" / "print_requests.json"
_lock = threading.Lock()

PENDING, CONFIRMED, WAITING, SENT, CANCELLED = (
    "pending_confirmation", "confirmed", "waiting_for_printer", "sent", "cancelled")
MAX_COPIES = 20
# A yes has to be spoken, so a confirm arriving this soon after the request was
# not Tommy answering - it is something chaining both calls on its own.
MIN_CONFIRM_DELAY_S = 4.0


def settings() -> dict:
    """ip / serial from config.json plus whether the access code is present. Never returns the code."""
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("printer") or {}
    except (OSError, ValueError):
        raw = {}
    return {"ip": str(raw.get("ip") or "").strip(), "serial": str(raw.get("serial") or "").strip(),
            "has_access_code": bool(os.getenv("ARGO_H2D_ACCESS_CODE", "").strip())}


def missing() -> list[str]:
    s = settings()
    out = []
    if not s["ip"]:
        out.append("the printer's IP address")
    if not s["serial"]:
        out.append("its serial number")
    if not s["has_access_code"]:
        out.append("the LAN access code")
    return out


def _load() -> dict:
    try:
        data = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REQUESTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, REQUESTS_FILE)


def _clean(text: str, limit: int = 160) -> str:
    return " ".join(str(text).split())[:limit]


def request_print(model: str, quantity: int = 1, material: str = "PETG", color: str = "",
                  source_url: str = "") -> dict:
    """Write down a print and wait for Tommy's yes. Nothing is sent."""
    model = _clean(model)
    if not model:
        raise ValueError("which model?")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, min(MAX_COPIES, quantity))
    url = _clean(source_url, 300)
    if url and not re.match(r"https://", url):
        url = ""  # only web links, never a local path
    req = {"id": secrets.token_hex(3), "model": model, "quantity": quantity,
           "material": _clean(material, 30) or "PETG", "color": _clean(color, 30),
           "source_url": url, "status": PENDING, "created": time.time()}
    with _lock:
        data = _load()
        for old in data.values():  # one open request at a time keeps "yes" unambiguous
            if old["status"] == PENDING:
                old["status"] = CANCELLED
        data[req["id"]] = req
        _save(data)
    return req


def describe(req: dict) -> str:
    colour = f" {req['color']}" if req.get("color") else ""
    return f"{req['quantity']} of {req['model']} in{colour} {req['material']}"


def _get(request_id: str) -> tuple[dict, dict]:
    data = _load()
    request_id = (request_id or "").strip()
    if not request_id:  # "yes" with no id means the one open request
        open_ = [r for r in data.values() if r["status"] == PENDING]
        request_id = open_[0]["id"] if len(open_) == 1 else ""
    return data, data.get(request_id) or {}


def confirm_print(request_id: str = "") -> dict:
    """Tommy said yes. Mark the request confirmed and send it if the printer is ready."""
    with _lock:
        data, req = _get(request_id)
        if not req:
            return {"ok": False, "message": "There is no print waiting for a yes."}
        if req["status"] != PENDING:
            return {"ok": False, "message": f"That print is already {req['status'].replace('_', ' ')}."}
        if time.time() - req.get("created", 0) < MIN_CONFIRM_DELAY_S:
            return {"ok": False, "message": "Ask Tommy first, then confirm once he has said yes."}
        gaps = missing()
        if gaps:
            req["status"] = WAITING
            data[req["id"]] = req
            _save(data)
            return {"ok": True, "sent": False, "request": req,
                    "message": "Saved it, but I can't send anything yet. I still need " + ", ".join(gaps) + "."}
        req["status"] = CONFIRMED
        data[req["id"]] = req
        _save(data)
    try:
        _send(req)
    except Exception as exc:  # nothing was sent, so say that
        with _lock:
            data = _load()
            if req["id"] in data:
                data[req["id"]]["status"] = WAITING
                _save(data)
        return {"ok": False, "sent": False, "request": req,
                "message": f"I could not send it to the printer: {type(exc).__name__}."}
    with _lock:
        data = _load()
        data[req["id"]]["status"] = SENT
        _save(data)
    return {"ok": True, "sent": True, "request": req, "message": f"Sent {describe(req)} to the H2D."}


def cancel_print(request_id: str = "") -> dict:
    with _lock:
        data, req = _get(request_id)
        if not req or req["status"] in (SENT, CANCELLED):
            return {"ok": False, "message": "There is no print to cancel."}
        req["status"] = CANCELLED
        data[req["id"]] = req
        _save(data)
    return {"ok": True, "message": "Cancelled that print request."}


def recent(limit: int = 8) -> list[dict]:
    rows = sorted(_load().values(), key=lambda r: r.get("created", 0), reverse=True)
    return rows[:limit]


def _send(req: dict) -> None:
    """Slice, upload and start the print on the H2D.

    Not built: it needs the real printer to develop against. Raising keeps the
    flow honest - a confirmed print is never reported as sent.
    """
    raise NotImplementedError("sending to the H2D is not built yet")


def status() -> dict:
    """Live printer status. Needs the printer set up and a status client."""
    gaps = missing()
    if gaps:
        return {"ok": False, "message": "The printer isn't set up yet. I need " + ", ".join(gaps) + "."}
    return {"ok": False, "message": "Live printer status isn't built yet."}
