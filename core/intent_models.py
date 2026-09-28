"""Public intent value objects and parser contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class IntentType(Enum):
    """Supported intent classifications."""
    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    COUNT = "count"
    MUSIC = "music"
    MUSIC_STOP = "music_stop"
    MUSIC_NEXT = "music_next"
    MUSIC_STATUS = "music_status"
    SLEEP = "sleep"
    SILENCE_OVERRIDE = "silence_override"  # "shut up" - jokey but obedient
    SYSTEM_HEALTH = "system_health"
    SYSTEM_STATUS = "system_status"
    SYSTEM_INFO = "system_info"
    SELF_DIAGNOSTICS = "self_diagnostics"  # ARGO checks itself
    AUDIO_ROUTING_STATUS = "audio_routing_status"
    AUDIO_ROUTING_CONTROL = "audio_routing_control"
    APP_STATUS = "app_status"
    APP_FOCUS_STATUS = "app_focus_status"
    APP_FOCUS_CONTROL = "app_focus_control"
    APP_LAUNCH = "app_launch"
    APP_CONTROL = "app_control"
    BLUETOOTH_STATUS = "bluetooth_status"
    BLUETOOTH_CONTROL = "bluetooth_control"
    VOLUME_STATUS = "volume_status"
    VOLUME_CONTROL = "volume_control"
    TIME_STATUS = "time_status"
    WORLD_TIME = "world_time"
    DEVELOP = "develop"
    ARGO_IDENTITY = "argo_identity"
    ARGO_GOVERNANCE = "argo_governance"
    UNKNOWN = "unknown"
    KNOWLEDGE_PHYSICS = "knowledge_physics"
    KNOWLEDGE_FINANCE = "knowledge_finance"
    KNOWLEDGE_TIME_SYSTEM = "knowledge_time_system"
    # Writing & productivity intents
    WRITE_EMAIL = "write_email"
    WRITE_BLOG = "write_blog"
    WRITE_DOCUMENT = "write_document"
    WRITE_NOTE = "write_note"
    EDIT_DRAFT = "edit_draft"
    LIST_DRAFTS = "list_drafts"
    READ_DRAFT = "read_draft"
    SEND_EMAIL = "send_email"
    SEARCH_DOCS = "search_docs"
    EXPORT_DATA = "export_data"
    # Smart home intents
    SMART_HOME_CONTROL = "smart_home_control"
    SMART_HOME_STATUS = "smart_home_status"
    # Reminders & calendar intents
    SET_REMINDER = "set_reminder"
    LIST_REMINDERS = "list_reminders"
    CANCEL_REMINDER = "cancel_reminder"
    CALENDAR_ADD = "calendar_add"
    CALENDAR_QUERY = "calendar_query"
    CANCEL_CALENDAR = "cancel_calendar"
    # Computer vision intents
    VISION_DESCRIBE = "vision_describe"
    VISION_READ_ERROR = "vision_read_error"
    VISION_QUESTION = "vision_question"
    # File system intents
    FILE_SEARCH = "file_search"
    FILE_LARGE = "file_large"
    FILE_RECENT = "file_recent"
    FILE_INFO = "file_info"
    # Task planner intent
    TASK_PLAN = "task_plan"


# ============================================================================
# 7) INTENT STRUCTURE
# ============================================================================
@dataclass
class Intent:
    """
    Structured intent extracted from text.
    
    Fields:
    - intent_type: What kind of intent (GREETING, QUESTION, COMMAND, MUSIC, UNKNOWN)
    - confidence: Simple score [0.0, 1.0] (1.0 = high confidence, 0.0 = low)
    - raw_text: Original input text (preserved for debugging)
    - keyword: Optional keyword extracted from command (for MUSIC intents)
    - artist: Optional artist extracted (for MUSIC intents)
    - title: Optional title extracted (for MUSIC intents)
    - modifiers: Optional modifiers extracted (for MUSIC intents)
    - is_generic_play: True if intent is a generic play request
    """
    intent_type: IntentType
    confidence: float
    raw_text: str
    keyword: Optional[str] = None
    artist: Optional[str] = None
    title: Optional[str] = None
    modifiers: Optional[List[str]] = None
    is_generic_play: bool = False
    serious_mode: bool = False
    unresolved: bool = False
    subintent: Optional[str] = None
    explicit_genre: bool = False
    action: Optional[str] = None
    target: Optional[str] = None

    def __str__(self) -> str:
        """Human-readable representation."""
        keyword_str = f", keyword='{self.keyword}'" if self.keyword else ""
        artist_str = f", artist='{self.artist}'" if self.artist else ""
        title_str = f", title='{self.title}'" if self.title else ""
        modifiers_str = f", modifiers={self.modifiers}" if self.modifiers else ""
        generic_str = ", generic_play=true" if self.is_generic_play else ""
        serious_str = ", serious_mode=true" if self.serious_mode else ""
        subintent_str = f", subintent={self.subintent}" if self.subintent else ""
        action_str = f", action={self.action}" if self.action else ""
        target_str = f", target={self.target}" if self.target else ""
        return (
            f"Intent({self.intent_type.value}, confidence={self.confidence:.2f}"
            f"{keyword_str}{artist_str}{title_str}{modifiers_str}{generic_str}{serious_str}{subintent_str}{action_str}{target_str}, text='{self.raw_text[:50]}')"
        )


# ============================================================================
# 8) INTENT PARSER INTERFACE
# ============================================================================
class IntentParser(ABC):
    """
    Base class for intent parsers.
    
    Single responsibility: Classify text into structured intents.
    """

    @abstractmethod
    def parse(self, text: str) -> Intent:
        """
        Parse text into structured intent.

        Args:
            text: Raw user input (from transcription)

        Returns:
            Intent object with type, confidence, and original text

        Raises:
            ValueError: If text is empty
        """
        pass
