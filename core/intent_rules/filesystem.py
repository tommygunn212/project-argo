"""Filesystem intent rules."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_filesystem_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── File System ────────────────────────────────────────────

    # FILE_LARGE: "find large files on D drive", "biggest files"
    if re.search(r"\b(large|big|huge|biggest|largest)\b.*\bfiles?\b", text_lower) or \
       re.search(r"\bfiles?\b.*\b(large|big|huge|biggest|largest|taking\s+space)\b", text_lower):
        return Intent(
            intent_type=IntentType.FILE_LARGE,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # FILE_RECENT: "what did I download today", "recent files", "latest downloads"
    if re.search(r"\b(recent|latest|new|today)\b.*\b(files?|downloads?)\b", text_lower) or \
       re.search(r"\bdownloads?\b.*\b(today|recent|latest|new)\b", text_lower) or \
       re.search(r"\bwhat\b.*\bdownload", text_lower):
        return Intent(
            intent_type=IntentType.FILE_RECENT,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # FILE_SEARCH: "find my tax documents", "search for PDF files", "locate the report"
    if re.search(r"\b(find|search|look\s+for|locate|where(?:'s| is| are))\b.*\b(files?|documents?|folders?|pdf|doc|spreadsheet|photos?|images?|videos?|music)\b", text_lower) or \
       re.search(r"\b(find|search|look\s+for|locate)\b.*\bon\s+[a-z]\s*(?:drive|:)", text_lower):
        return Intent(
            intent_type=IntentType.FILE_SEARCH,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    return None
