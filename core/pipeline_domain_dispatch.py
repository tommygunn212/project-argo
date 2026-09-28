"""Ordered domain-intent dispatch for the classic conversation pipeline.

The handlers remain on :class:`ArgoPipeline`; this module only owns the routing
table so ``handle_user_text`` does not need one branch per intent.
"""

from __future__ import annotations

from typing import Any

from core.intent_parser import IntentType


_DOMAIN_HANDLERS = {
    IntentType.WRITE_EMAIL: "_respond_with_write_email",
    IntentType.WRITE_BLOG: "_respond_with_write_blog",
    IntentType.WRITE_DOCUMENT: "_respond_with_write_document",
    IntentType.WRITE_NOTE: "_respond_with_write_note",
    IntentType.EDIT_DRAFT: "_respond_with_edit_draft",
    IntentType.LIST_DRAFTS: "_respond_with_list_drafts",
    IntentType.READ_DRAFT: "_respond_with_read_draft",
    IntentType.SEND_EMAIL: "_respond_with_send_email",
    IntentType.SEARCH_DOCS: "_respond_with_search_docs",
    IntentType.EXPORT_DATA: "_respond_with_export_data",
    IntentType.SMART_HOME_CONTROL: "_respond_with_smart_home_control",
    IntentType.SMART_HOME_STATUS: "_respond_with_smart_home_status",
    IntentType.SET_REMINDER: "_respond_with_set_reminder",
    IntentType.LIST_REMINDERS: "_respond_with_list_reminders",
    IntentType.CANCEL_REMINDER: "_respond_with_cancel_reminder",
    IntentType.CALENDAR_ADD: "_respond_with_calendar_add",
    IntentType.CALENDAR_QUERY: "_respond_with_calendar_query",
    IntentType.CANCEL_CALENDAR: "_respond_with_cancel_calendar",
    IntentType.VISION_DESCRIBE: "_respond_with_vision_describe",
    IntentType.VISION_READ_ERROR: "_respond_with_vision_read_error",
    IntentType.VISION_QUESTION: "_respond_with_vision_question",
    IntentType.FILE_SEARCH: "_respond_with_file_search",
    IntentType.FILE_LARGE: "_respond_with_file_large",
    IntentType.FILE_RECENT: "_respond_with_file_recent",
    IntentType.FILE_INFO: "_respond_with_file_info",
    IntentType.TASK_PLAN: "_respond_with_task_plan",
}


def dispatch_domain_intent(
    pipeline: Any,
    intent: Any,
    user_text: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Dispatch a domain intent, returning whether its handler completed it."""
    if intent is None:
        return False

    handler_name = _DOMAIN_HANDLERS.get(intent.intent_type)
    if handler_name is None:
        return False

    handler = getattr(pipeline, handler_name)
    return bool(handler(intent, user_text, interaction_id, replay_mode, overrides))
