"""Writing and productivity intent rules."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_writing_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── Writing & Productivity intents (BEFORE system health / hardware) ──

    # SEND_EMAIL: "send that email", "send the email", "send the last email"
    if re.search(r"\bsend\b.*\b(email|mail|draft)\b", text_lower):
        return Intent(
            intent_type=IntentType.SEND_EMAIL,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # WRITE_EMAIL: "write an email to…", "draft an email…", "email Paul about…"
    if re.search(r"\b(write|draft|compose|create)\b.*\b(email|e-mail|mail)\b", text_lower) or \
       re.search(r"^email\s+\w+", text_lower):
        return Intent(
            intent_type=IntentType.WRITE_EMAIL,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # WRITE_BLOG: "write a blog post about…", "draft a blog…"
    if re.search(r"\b(write|draft|compose|create)\b.*\b(blog|article|post)\b", text_lower):
        return Intent(
            intent_type=IntentType.WRITE_BLOG,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # WRITE_DOCUMENT: "write a letter…", "draft a document…"
    if re.search(r"\b(write|draft|compose|create)\b.*\b(letter|document|doc)\b", text_lower):
        return Intent(
            intent_type=IntentType.WRITE_DOCUMENT,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # WRITE_NOTE: "take a note", "save a note", "note that…", "jot down…"
    if re.search(r"\b(take|save|make|jot|write|capture)\b.*\b(note|memo|idea|thought)\b", text_lower) or \
       re.search(r"^note\s+that\b", text_lower) or \
       re.search(r"\bjot\s+(this\s+)?down\b", text_lower) or \
       re.search(r"^write\s+(this\s+)?down\b", text_lower):
        return Intent(
            intent_type=IntentType.WRITE_NOTE,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # EDIT_DRAFT: "edit the draft", "make it shorter", "revise the email"
    if re.search(r"\b(edit|revise|rewrite|rework|shorten|lengthen|fix)\b.*\b(draft|email|blog|note|post)\b", text_lower) or \
       re.search(r"\bmake\s+(it|the\s+\w+)\s+(shorter|longer|funnier|more\s+\w+|less\s+\w+|formal|casual|professional)\b", text_lower):
        return Intent(
            intent_type=IntentType.EDIT_DRAFT,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # LIST_DRAFTS: "list my drafts", "show drafts", "what drafts do I have"
    if re.search(r"\b(list|show|what)\b.*\b(draft|drafts)\b", text_lower):
        return Intent(
            intent_type=IntentType.LIST_DRAFTS,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # READ_DRAFT: "read my last draft", "read the draft", "open the draft"
    if re.search(r"\b(read|open)\b.*\b(last|latest|recent)?\s*(draft)\b", text_lower):
        return Intent(
            intent_type=IntentType.READ_DRAFT,
            confidence=0.94,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # SEARCH_DOCS: "search my documents", "find the email about…", "search drafts for…"
    # Guard: skip if clearly a filesystem query (drive reference, file types, size words)
    _fs_search_guard = re.search(r"\bon\s+[a-z]\s*drive\b|\b(pdf|xlsx|csv|mp3|mp4|jpg|png|exe|zip)\b|\b(large|big|huge|biggest|largest|recent|latest|downloaded)\b|\b(photos?|images?|videos?|music|spreadsheets?)\b", text_lower)
    if not _fs_search_guard and re.search(r"\b(search|find|look\s+for|look\s+up)\b.*\b(documents?|drafts?|emails?|blogs?|notes?|files?|writings?)\b", text_lower):
        return Intent(
            intent_type=IntentType.SEARCH_DOCS,
            confidence=0.94,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # EXPORT_DATA: "export to spreadsheet", "create a spreadsheet", "export my facts"
    if re.search(r"\b(export|spreadsheet|csv)\b", text_lower):
        return Intent(
            intent_type=IntentType.EXPORT_DATA,
            confidence=0.94,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    return None
