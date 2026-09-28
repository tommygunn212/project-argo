"""Draft retrieval, delivery, search, and export responses."""

from __future__ import annotations

from typing import Any, Protocol

from tools.email_sender import is_email_configured, send_draft
from tools.writing import (
    export_brain_facts_to_csv,
    export_drafts_to_csv,
    get_latest_draft,
    list_drafts,
    parse_spreadsheet_request,
    search_drafts,
)


class PipelineDraftResponseMixin:
    def _respond_with_list_drafts(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """List recent drafts."""
        self.logger.info(f"[WRITING] List drafts: {user_text}")
        import re as _re
        category = None
        if _re.search(r"\bemail", user_text, _re.IGNORECASE):
            category = "email"
        elif _re.search(r"\bblog", user_text, _re.IGNORECASE):
            category = "blog"
        elif _re.search(r"\bnote", user_text, _re.IGNORECASE):
            category = "note"

        drafts = list_drafts(category=category, limit=5)
        if not drafts:
            cat_label = f"{category} " if category else ""
            return self._deliver_canonical_response(
                f"No {cat_label}drafts found.",
                interaction_id, replay_mode, overrides,
            )

        lines = []
        for i, d in enumerate(drafts, 1):
            lines.append(f"{i}. {d.category}: {d.name}, {d.word_count} words")
        response = f"You have {len(drafts)} recent drafts. " + ". ".join(lines) + "."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_read_draft(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Read back the most recent draft."""
        self.logger.info(f"[WRITING] Read draft: {user_text}")
        import re as _re
        category = None
        if _re.search(r"\bemail", user_text, _re.IGNORECASE):
            category = "email"
        elif _re.search(r"\bblog", user_text, _re.IGNORECASE):
            category = "blog"
        elif _re.search(r"\bnote", user_text, _re.IGNORECASE):
            category = "note"

        draft = get_latest_draft(category=category)
        if not draft:
            return self._deliver_canonical_response(
                "No drafts to read.",
                interaction_id, replay_mode, overrides,
            )

        # Truncate for TTS (long documents shouldn't be fully read aloud)
        content = draft.content
        words = content.split()
        if len(words) > 150:
            content = " ".join(words[:150]) + "... That's the first 150 words. The full draft is saved."

        response = f"Here's your latest {draft.category} draft: {content}"
        return self._deliver_canonical_response(
            response, interaction_id, replay_mode, overrides,
            enforce_confidence=False,
            suppress_barge_in_seconds=2.0,
        )

    def _respond_with_send_email(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Send the most recent email draft."""
        self.logger.info(f"[WRITING] Send email: {user_text}")
        if not is_email_configured():
            return self._deliver_canonical_response(
                "Email sending isn't configured yet. Add your email settings to config dot json first.",
                interaction_id, replay_mode, overrides,
            )

        draft = get_latest_draft(category="email")
        if not draft:
            return self._deliver_canonical_response(
                "No email draft to send. Write an email first.",
                interaction_id, replay_mode, overrides,
            )

        # Parse out the To field from the draft
        to_address = ""
        for line in draft.content.split("\n"):
            if line.startswith("To:"):
                to_address = line[3:].strip()
                break

        if not to_address or "@" not in to_address:
            return self._deliver_canonical_response(
                f"The email draft is addressed to '{to_address}' but I need a full email address to send it. "
                f"Update the draft with the recipient's email address.",
                interaction_id, replay_mode, overrides,
            )

        success = send_draft(str(draft.path), to_address)
        if success:
            response = f"Email sent to {to_address} successfully."
        else:
            response = "Email sending failed. Check the logs for details."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_search_docs(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Search across drafts and documents."""
        self.logger.info(f"[WRITING] Search docs: {user_text}")
        import re as _re
        # Extract the search query (remove trigger words)
        query = _re.sub(
            r"^(search|find|look\s+for|look\s+up)\s+(my\s+)?(documents?|drafts?|emails?|blogs?|notes?|files?|writings?)\s*(for|about|on)?\s*",
            "", user_text, flags=_re.IGNORECASE,
        ).strip()
        if not query:
            query = user_text

        results = search_drafts(query, limit=5)
        if not results:
            return self._deliver_canonical_response(
                f"No documents found matching '{query}'.",
                interaction_id, replay_mode, overrides,
            )

        lines = []
        for i, d in enumerate(results, 1):
            lines.append(f"{i}. {d.category}: {d.name}")
        response = f"Found {len(results)} matches for '{query}'. " + ". ".join(lines) + "."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_export_data(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Export data to CSV spreadsheet."""
        self.logger.info(f"[WRITING] Export data: {user_text}")
        parsed = parse_spreadsheet_request(user_text)
        source = parsed.get("data_source", "brain_facts")

        try:
            if source == "brain_facts":
                path = export_brain_facts_to_csv()
                response = f"Brain facts exported to spreadsheet: {path.name}."
            elif source == "drafts":
                path = export_drafts_to_csv()
                response = f"Draft list exported to spreadsheet: {path.name}."
            elif source == "notes":
                path = export_drafts_to_csv(category="note")
                response = f"Notes exported to spreadsheet: {path.name}."
            else:
                path = export_brain_facts_to_csv()
                response = f"Data exported to spreadsheet: {path.name}."
        except Exception as e:
            self.logger.error(f"[WRITING] Export failed: {e}")
            response = "Export failed. Check the logs for details."

        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)


class DraftResponseHost(Protocol):
    """Small host contract required by draft and document-library responses."""

    logger: Any

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool: ...


class PipelineDraftResponseService(PipelineDraftResponseMixin):
    """Composed draft handlers backed by canonical response delivery."""

    def __init__(self, host: DraftResponseHost):
        self._host = host

    @property
    def logger(self) -> Any:
        return self._host.logger

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool:
        return self._host._deliver_canonical_response(message, *args, **kwargs)

