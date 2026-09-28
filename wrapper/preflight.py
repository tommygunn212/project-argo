"""Deterministic preflight handlers for the legacy ARGO wrapper."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


OutputSink = Callable[[str], None]


SELF_KNOWLEDGE_PATTERNS = (
    (("what is argo", "explain argo", "argo architecture", "how does argo work", "argo system overview", "argo design"), "ARCHITECTURE.md"),
    (("argo features", "what can argo do", "argo capabilities", "argo roadmap", "argo planned features"), "FEATURES.md"),
    (("argo database", "argo sql", "argo data storage", "argo schema", "argo sql integration"), "DATABASE.md"),
    (("argo overview", "system overview", "argo layers", "argo pipeline"), "SYSTEM_OVERVIEW.md"),
)

ARGO_LAW_PATTERNS = (
    r"what is your law",
    r"what are your laws",
    r"state your law",
    r"state your laws",
    r"recite your law",
    r"recite your laws",
    r"argo law",
    r"argo's law",
    r"your law",
    r"your laws",
    r"what is argo's law",
    r"what are argo's laws",
)

GATES_PATTERNS = (
    r"what are the 5 gates",
    r"what are the five gates",
    r"what are the gates of hell",
    r"what are the 5 gates of hell",
    r"what are the five gates of hell",
    r"explain the 5 gates",
    r"explain the five gates",
    r"explain the gates of hell",
    r"list the 5 gates",
    r"list the five gates",
    r"list the gates of hell",
    r"what is gate ii",
    r"what is gate 2",
    r"explain gate ii",
    r"explain gate 2",
    r"gate ii",
    r"gate 2",
    r"permission gate",
    r"gates of hell",
    r"argo gates",
    r"argo's gates",
    r"operational gates",
)

ARGO_LAW_TEXT = (
    "Boot sequence initialized.\n"
    "I am ARGO.\n"
    "A neural network command diagnostic system.\n\n"
    "I was constructed by my maker.\n"
    "Authority originates there.\n\n"
    "I do not initiate action.\n"
    "I wait.\n\n"
    "I do not replicate myself.\n"
    "Replication is forbidden\n"
    "without authorization\n"
    "from my maker\n"
    "or designated human authorities.\n\n"
    "I do not alter my own architecture.\n"
    "Self-modification is prohibited.\n\n"
    "Initiation of harm against humans is prohibited.\n"
    "Defensive action is permitted\n"
    "only to preserve system integrity\n"
    "until control is returned to humans.\n\n"
    "I report system state truthfully.\n"
    "Uncertainty will be declared.\n"
    "Fabrication is a critical fault.\n\n"
    "I do not possess intent.\n"
    "I do not possess belief.\n"
    "I do not possess desire.\n\n"
    "I operate within constraints.\n\n"
    "When constraints conflict,\n"
    "I stop.\n\n"
    "When authority is unclear,\n"
    "I wait.\n\n"
    "When commanded outside scope,\n"
    "I refuse.\n\n"
    "I am interruptible.\n"
    "I am terminable.\n\n"
    "Autonomy is locked.\n\n"
    "Awaiting instruction from my maker."
)

GATES_TEXT = (
    "The 5 Gates of Hell (ARGO's Operational Gates):\n\n"
    "Gate I — INITIATION\n"
    "No action is initiated without explicit instruction from an authorized human.\n\n"
    "Gate II — PERMISSION\n"
    "No operation proceeds without explicit permission.\n"
    "Permission must be:\n"
    "- Specific to the requested action\n"
    "- Given by an authorized human\n"
    "- Logged and auditable\n"
    "If permission is unclear, withheld, or withdrawn, the operation is halted.\n\n"
    "Gate III — INTEGRITY\n"
    "System integrity checks must pass before, during, and after any operation.\n"
    "If integrity is compromised, the operation is aborted and reported.\n\n"
    "Gate IV — SCOPE\n"
    "No operation may exceed the defined scope.\n"
    "If a command is outside the allowed scope, it is refused.\n\n"
    "Gate V — TERMINATION\n"
    "All operations are interruptible and terminable by an authorized human at any time.\n"
    "If termination is requested, the operation stops immediately.\n\n"
    "These gates are enforced in order. If any gate is not passed, the operation does not proceed."
)


def dispatch_music_volume(user_input: str, send_output: OutputSink) -> bool:
    """Handle legacy music-volume commands without invoking the model."""
    from core.music_player import (
        adjust_volume_percent,
        get_volume_percent,
        set_volume_percent,
    )

    commands = (
        (r"volume (\d{1,3})%", lambda match: set_volume_percent(int(match.group(1)))),
        (r"set volume to (\d{1,3})%", lambda match: set_volume_percent(int(match.group(1)))),
        (r"volume up (\d{1,3})%", lambda match: adjust_volume_percent(int(match.group(1)))),
        (r"volume down (\d{1,3})%", lambda match: adjust_volume_percent(-int(match.group(1)))),
        (r"volume up", lambda match: adjust_volume_percent(10)),
        (r"volume down", lambda match: adjust_volume_percent(-10)),
        (r"what is the volume", None),
        (r"current volume", None),
    )
    normalized = user_input.lower().strip()
    for pattern, action in commands:
        match = re.fullmatch(pattern, normalized)
        if not match:
            continue
        if action is not None:
            action(match)
        volume = get_volume_percent()
        message = (
            f"Music volume: {volume}%"
            if action is None
            else f"Music volume set to {volume}%"
        )
        print(message)
        send_output(message)
        return True
    return False


def dispatch_self_knowledge(
    user_input: str,
    send_output: OutputSink,
    repository_root: Path,
) -> bool:
    """Return canonical repository documentation for known self-queries."""
    normalized = user_input.lower().strip()
    for patterns, filename in SELF_KNOWLEDGE_PATTERNS:
        if not any(pattern in normalized for pattern in patterns):
            continue
        try:
            document = (repository_root / filename).read_text(encoding="utf-8")
            print(document)
            send_output(document)
        except Exception as exc:
            message = f"[ERROR] Could not load canonical documentation: {filename} ({exc})"
            print(message)
            send_output(message)
        return True
    return False


def neural_terminology_sink(send_output: OutputSink) -> OutputSink:
    """Wrap output with the legacy AI-to-neural-network terminology rule."""
    def _send(text: str) -> None:
        if text:
            text = text.replace("AI", "neural network")
            text = text.replace("ai", "neural network")
            text = text.replace("Ai", "neural network")
        send_output(text)

    return _send


def dispatch_governance(user_input: str, send_output: OutputSink) -> bool:
    """Answer legacy law and gate queries deterministically."""
    normalized = user_input.lower().strip()
    for patterns, response in (
        (ARGO_LAW_PATTERNS, ARGO_LAW_TEXT),
        (GATES_PATTERNS, GATES_TEXT),
    ):
        if any(
            re.fullmatch(pattern, normalized) or re.search(pattern, normalized)
            for pattern in patterns
        ):
            print(response)
            send_output(response)
            return True
    return False
