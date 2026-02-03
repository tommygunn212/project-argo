"""ARGO version registry.

Single source of truth for runtime versioning.
"""

CURRENT_VERSION = "1.6.1"
CURRENT_MILESTONE = "deterministic-core-stabilization"
CURRENT_DATE = "2026-02-02"

VERSION_HISTORY = [
    {
        "version": "1.0.0-voice-core",
        "date": "2026-01-22",
        "notes": "Voice-core baseline, state machine + STOP dominance",
    },
    {
        "version": "1.4.4-input-shell",
        "date": "2026-01-22",
        "notes": "Input shell wrapper updates",
    },
    {
        "version": "1.5.0",
        "date": "2026-01-28",
        "notes": "Deterministic system health + disk queries; music hardening",
    },
    {
        "version": "1.6.0",
        "date": "2026-02-01",
        "notes": "Behavioral stability + UX intelligence release",
    },
    {
        "version": "1.6.1",
        "date": CURRENT_DATE,
        "notes": "Deterministic core stabilization; canonical commands bypass STT confidence gates",
    },
]


def get_version():
    return {
        "version": CURRENT_VERSION,
        "milestone": CURRENT_MILESTONE,
        "date": CURRENT_DATE,
        "history": VERSION_HISTORY,
    }
