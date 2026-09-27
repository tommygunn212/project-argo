"""Drafts saved to disk. Nothing here sends anything.
"""

from __future__ import annotations

from core.realtime_tools._base import capability

__all__ = [
    "DRAFT_KINDS",
    "draft_write",
    "drafts_list",
    "draft_read",
    "email_status",
]


DRAFT_KINDS = ("email", "document", "blog", "note")


@capability
def draft_write(kind: str, title: str, body: str, recipient: str = "") -> dict:
    """Save a draft (email, document, blog or note) to ARGO's drafts folder.

    This writes a file. It does not send anything - see email_status().
    """
    from tools import writing

    wanted = (kind or "").strip().lower()
    if wanted not in DRAFT_KINDS:
        return {"ok": False, "error": "unknown_kind", "requested": kind,
                "kinds": list(DRAFT_KINDS)}
    if not (body or "").strip():
        return {"ok": False, "error": "empty_body", "kind": wanted,
                "message": "There was nothing to write into the draft."}

    if wanted == "email":
        draft = writing.draft_email(recipient or "", title or "", body)
    elif wanted == "document":
        draft = writing.draft_document(title or "Untitled", body, recipient=recipient or "")
    elif wanted == "blog":
        draft = writing.draft_blog(title or "Untitled", body)
    else:
        draft = writing.save_note(body, title=title or None)

    return {"ok": True, "kind": wanted, "title": title,
            "recipient": recipient or None,
            "name": getattr(draft, "name", None),
            "path": str(getattr(draft, "path", "")) or None,
            "message": f"Saved the {wanted} draft."}


@capability
def drafts_list(category: str = "", limit: int = 10) -> dict:
    from tools import writing

    rows = writing.list_drafts(category=category or None, limit=max(1, int(limit))) or []
    return {
        "ok": True,
        "count": len(rows),
        "category": category or "all",
        "drafts": [{"name": d.name, "category": d.category, "path": str(d.path)} for d in rows],
    }


@capability
def draft_read(name: str) -> dict:
    """Read back a saved draft by name, so ARGO can recite it."""
    from tools import writing

    def key(value: str) -> str:
        # Draft filenames are slugged ("readback_probe"); people say
        # "readback probe". Compare with the punctuation stripped out.
        return "".join(ch for ch in (value or "").lower() if ch.isalnum())

    wanted = key(name)
    if not wanted:
        return {"ok": False, "error": "no_name"}
    for draft in writing.list_drafts(limit=200) or []:
        if wanted in key(draft.name):
            text = draft.content
            return {"ok": True, "name": draft.name, "category": draft.category,
                    "path": str(draft.path), "characters": len(text), "content": text}
    return {"ok": False, "error": "not_found", "requested": name}


@capability
def email_status() -> dict:
    """Whether sending is configured. Sending itself is not wired to voice."""
    from tools.email_sender import is_email_configured

    configured = bool(is_email_configured())
    return {
        "ok": True,
        "configured": configured,
        "can_send_by_voice": False,
        "message": (
            "Email sending is configured, but I'm not wired to send by voice yet."
            if configured else
            "Email sending isn't set up - there are no mail credentials configured."
        ),
    }
