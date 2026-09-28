"""Fail-closed guard for locally handled classic-pipeline intents."""

from __future__ import annotations

from typing import Any

from core.intent_parser import IntentType


def block_restricted_llm_fallback(
    pipeline: Any,
    intent: Any,
    user_text: str,
    safe_utterance: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Prevent local-only intents from leaking into the general LLM path."""
    restricted_llm_intents = {
        IntentType.MUSIC,
        IntentType.MUSIC_STOP,
        IntentType.MUSIC_NEXT,
        IntentType.MUSIC_STATUS,
        IntentType.SYSTEM_HEALTH,
        IntentType.SYSTEM_STATUS,
        IntentType.BLUETOOTH_STATUS,
        IntentType.BLUETOOTH_CONTROL,
        IntentType.AUDIO_ROUTING_STATUS,
        IntentType.AUDIO_ROUTING_CONTROL,
        IntentType.APP_STATUS,
        IntentType.APP_FOCUS_STATUS,
        IntentType.APP_FOCUS_CONTROL,
        IntentType.APP_LAUNCH,
        IntentType.APP_CONTROL,
        IntentType.VOLUME_STATUS,
        IntentType.VOLUME_CONTROL,
        IntentType.TIME_STATUS,
        IntentType.WORLD_TIME,
        IntentType.ARGO_IDENTITY,
        IntentType.ARGO_GOVERNANCE,
        # Writing & productivity
        IntentType.WRITE_EMAIL,
        IntentType.WRITE_BLOG,
        IntentType.WRITE_DOCUMENT,
        IntentType.WRITE_NOTE,
        IntentType.EDIT_DRAFT,
        IntentType.LIST_DRAFTS,
        IntentType.READ_DRAFT,
        IntentType.SEND_EMAIL,
        IntentType.SEARCH_DOCS,
        IntentType.EXPORT_DATA,
        # Smart home
        IntentType.SMART_HOME_CONTROL,
        IntentType.SMART_HOME_STATUS,
        # Reminders & calendar
        IntentType.SET_REMINDER,
        IntentType.LIST_REMINDERS,
        IntentType.CANCEL_REMINDER,
        IntentType.CALENDAR_ADD,
        IntentType.CALENDAR_QUERY,
        IntentType.CANCEL_CALENDAR,
        # Computer vision
        IntentType.VISION_DESCRIBE,
        IntentType.VISION_READ_ERROR,
        IntentType.VISION_QUESTION,
        # File system
        IntentType.FILE_SEARCH,
        IntentType.FILE_LARGE,
        IntentType.FILE_RECENT,
        IntentType.FILE_INFO,
        # Task planner
        IntentType.TASK_PLAN,
    }
    if intent and intent.intent_type in restricted_llm_intents:
        leak_messages = {
            IntentType.MUSIC: "Music control routing failed. Please repeat the command.",
            IntentType.MUSIC_STOP: "Music stop failed to route. Say stop music again.",
            IntentType.MUSIC_NEXT: "Skip command failed to route. Say next track again.",
            IntentType.MUSIC_STATUS: "Music status is handled locally. Ask again.",
            IntentType.SYSTEM_HEALTH: "System health is handled locally. Please ask again.",
            IntentType.SYSTEM_STATUS: "System status is handled locally. Please ask again.",
            IntentType.BLUETOOTH_STATUS: "Bluetooth status is handled locally. Ask again.",
            IntentType.BLUETOOTH_CONTROL: "Bluetooth control is handled locally. Please repeat the command.",
            IntentType.AUDIO_ROUTING_STATUS: "Audio routing status is handled locally. Ask again.",
            IntentType.AUDIO_ROUTING_CONTROL: "Audio routing control is handled locally. Please repeat the command.",
            IntentType.APP_STATUS: "App status is handled locally. Ask again.",
            IntentType.APP_FOCUS_STATUS: "App focus status is handled locally. Ask again.",
            IntentType.APP_FOCUS_CONTROL: "App focus control is handled locally. Please repeat the command.",
            IntentType.APP_LAUNCH: "App launch is handled locally. Please repeat the command.",
            IntentType.APP_CONTROL: "App control is handled locally. Please repeat the command.",
            IntentType.VOLUME_STATUS: "System volume status is handled locally. Ask again.",
            IntentType.VOLUME_CONTROL: "System volume control is handled locally. Please repeat the command.",
            IntentType.TIME_STATUS: "Time status is handled locally. Ask again.",
            IntentType.WORLD_TIME: "World time is handled locally. Ask again.",
            IntentType.ARGO_IDENTITY: "Identity answers are deterministic. Ask again if needed.",
            IntentType.ARGO_GOVERNANCE: "Governance answers are deterministic. Ask again if needed.",
            IntentType.WRITE_EMAIL: "Email drafting failed to route. Say it again.",
            IntentType.WRITE_BLOG: "Blog writing failed to route. Say it again.",
            IntentType.WRITE_DOCUMENT: "Document drafting failed to route. Say it again.",
            IntentType.WRITE_NOTE: "Note saving failed to route. Say it again.",
            IntentType.EDIT_DRAFT: "Draft editing failed to route. Say it again.",
            IntentType.LIST_DRAFTS: "Draft listing failed to route. Say it again.",
            IntentType.READ_DRAFT: "Draft reading failed to route. Say it again.",
            IntentType.SEND_EMAIL: "Email sending failed to route. Say it again.",
            IntentType.SEARCH_DOCS: "Document search failed to route. Say it again.",
            IntentType.EXPORT_DATA: "Export failed to route. Say it again.",
            IntentType.SMART_HOME_CONTROL: "Smart home control failed to route. Say it again.",
            IntentType.SMART_HOME_STATUS: "Smart home status failed to route. Say it again.",
            IntentType.SET_REMINDER: "Reminder failed to route. Say it again.",
            IntentType.LIST_REMINDERS: "Reminder listing failed to route. Say it again.",
            IntentType.CANCEL_REMINDER: "Reminder cancellation failed to route. Say it again.",
            IntentType.CALENDAR_ADD: "Calendar event failed to route. Say it again.",
            IntentType.CALENDAR_QUERY: "Calendar query failed to route. Say it again.",
            IntentType.CANCEL_CALENDAR: "Calendar cancellation failed to route. Say it again.",
            IntentType.VISION_DESCRIBE: "Screen capture failed to route. Say it again.",
            IntentType.VISION_READ_ERROR: "Error reading failed to route. Say it again.",
            IntentType.VISION_QUESTION: "Vision question failed to route. Say it again.",
            IntentType.FILE_SEARCH: "File search failed to route. Say it again.",
            IntentType.FILE_LARGE: "Large file search failed to route. Say it again.",
            IntentType.FILE_RECENT: "Recent files failed to route. Say it again.",
            IntentType.FILE_INFO: "File info failed to route. Say it again.",
            IntentType.TASK_PLAN: "Task planning failed to route. Say it again.",
        }
        leak_msg = leak_messages.get(intent.intent_type, "Routing error. Please repeat the request.")
        safe_text = safe_utterance or (user_text or "")
        if intent.intent_type == IntentType.SYSTEM_STATUS:
            pipeline.logger.error("[CANONICAL LEAK] SYSTEM_STATUS reached LLM – BLOCKING")
        else:
            pipeline.logger.error(f"[CANONICAL LEAK] intent={intent.intent_type} text=\"{safe_text}\"")
        pipeline._deliver_canonical_response(leak_msg, interaction_id, replay_mode, overrides)
        return True

    return False
