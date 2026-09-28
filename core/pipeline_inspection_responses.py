"""Vision and filesystem response handlers for the classic pipeline."""

from __future__ import annotations

import os
from typing import Any, Protocol

from tools.filesystem import (
    find_large_files,
    find_recent_files,
    format_file_info_for_speech,
    format_file_list_for_speech,
    get_file_info,
    parse_filesystem_command,
    search_by_extension,
    search_files,
)
from tools.vision import (
    analyze_screen_with_question,
    describe_screen,
    parse_vision_command,
    read_screen_error,
)


class PipelineInspectionResponseMixin:
    # ── Computer Vision Handlers ──────────────────────────────────

    def _respond_with_vision_describe(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Capture screenshot and describe what's on screen."""
        self.logger.info(f"[VISION] Describe screen: {user_text}")
        response = describe_screen(user_prompt="Describe what you see on my screen.")
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_vision_read_error(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Capture screenshot and read error messages."""
        self.logger.info(f"[VISION] Read error: {user_text}")
        response = read_screen_error()
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_vision_question(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Capture screenshot and answer a specific question about it."""
        self.logger.info(f"[VISION] Question: {user_text}")
        parsed = parse_vision_command(user_text)
        question = parsed.get("question", user_text)
        if not question:
            question = user_text
        response = analyze_screen_with_question(question)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    # ── File System Handlers ──────────────────────────────────────

    def _respond_with_file_search(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Search for files by name or type."""
        self.logger.info(f"[FILESYSTEM] Search: {user_text}")
        parsed = parse_filesystem_command(user_text)
        query = parsed["query"]
        roots = [parsed["drive"]] if parsed["drive"] else None
        extensions = parsed.get("extensions")

        if extensions and not query:
            files = search_by_extension(extensions, roots=roots)
        else:
            files = search_files(query, roots=roots, extensions=extensions)

        response = format_file_list_for_speech(files, label="matching files")
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_file_large(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Find large files on a drive."""
        self.logger.info(f"[FILESYSTEM] Large files: {user_text}")
        parsed = parse_filesystem_command(user_text)
        root = parsed.get("drive") or "C:\\Users"
        min_size = parsed.get("min_size_mb") or 100.0
        files = find_large_files(root, min_size_mb=min_size)
        response = format_file_list_for_speech(files, label="large files")
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_file_recent(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Show recently modified files / downloads."""
        self.logger.info(f"[FILESYSTEM] Recent files: {user_text}")
        parsed = parse_filesystem_command(user_text)
        hours = parsed.get("hours") or 24
        files = find_recent_files(hours=hours)
        response = format_file_list_for_speech(files, label="recent downloads")
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_file_info(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Get info about a specific file or directory."""
        self.logger.info(f"[FILESYSTEM] File info: {user_text}")
        parsed = parse_filesystem_command(user_text)
        path = parsed.get("query", "")
        if not path or not os.path.exists(path):
            return self._deliver_canonical_response(
                "I couldn't find that path. Try giving me the full file path.",
                interaction_id, replay_mode, overrides,
            )
        info = get_file_info(path)
        response = format_file_info_for_speech(info)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)


class InspectionResponseHost(Protocol):
    """Small host contract required by vision and filesystem responses."""

    logger: Any

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool: ...


class PipelineInspectionService(PipelineInspectionResponseMixin):
    """Composed inspection handlers backed by a narrow pipeline interface."""

    def __init__(self, host: InspectionResponseHost):
        self._host = host

    @property
    def logger(self) -> Any:
        return self._host.logger

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool:
        return self._host._deliver_canonical_response(message, *args, **kwargs)

