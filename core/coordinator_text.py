"""Pure text and similarity helpers used by coordinator stages."""

from __future__ import annotations

import re


def extract_code_block(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"```(?:python)?\n([\s\S]*?)```", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip("\n") or None


def strip_code_blocks(text: str) -> str:
    if not text:
        return text
    return re.sub(r"```[\s\S]*?```", "", text).strip()


def infer_sandbox_filename(user_text: str, response_text: str) -> str:
    response_match = re.search(r"([a-zA-Z0-9_\-]+\.py)", response_text)
    if response_match:
        return response_match.group(1)
    user_match = re.search(r"([a-zA-Z0-9_\-]+\.py)", user_text)
    if user_match:
        return user_match.group(1)
    lowered = user_text.lower()
    if "storage" in lowered or "disk" in lowered or "space" in lowered:
        return "storage_check.py"
    if "cpu" in lowered or "monitor" in lowered:
        return "cpu_monitor.py"
    return "sandbox_tool.py"


def similarity_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_normalized = left.strip().lower()
    right_normalized = right.strip().lower()
    if left_normalized == right_normalized:
        return 1.0
    max_length = max(len(left_normalized), len(right_normalized))
    if max_length == 0:
        return 0.0
    return 1.0 - levenshtein_distance(left_normalized, right_normalized) / max_length


def levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous_row = list(range(len(right) + 1))
    for row_index, left_character in enumerate(left, start=1):
        current_row = [row_index]
        for column_index, right_character in enumerate(right, start=1):
            insert_cost = current_row[column_index - 1] + 1
            delete_cost = previous_row[column_index] + 1
            replace_cost = previous_row[column_index - 1] + (
                0 if left_character == right_character else 1
            )
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        previous_row = current_row
    return previous_row[-1]
