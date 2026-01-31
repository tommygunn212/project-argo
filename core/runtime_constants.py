"""Immutable runtime constants for gates and laws."""

from enum import Enum


class Gate(str, Enum):
    VALIDATION = "VALIDATION"
    PERMISSION = "PERMISSION"
    SAFETY = "SAFETY"
    RESOURCE = "RESOURCE"
    AUDIT = "AUDIT"


GATES_ORDER = (
    Gate.VALIDATION,
    Gate.PERMISSION,
    Gate.SAFETY,
    Gate.RESOURCE,
    Gate.AUDIT,
)


LAWS = (
    "Do not harm users.",
    "Obey authorized commands.",
    "Protect user privacy.",
    "Maintain auditability.",
    "Never self-modify code or rules.",
)
