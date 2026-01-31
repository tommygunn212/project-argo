"""
Canonical registries for ARGO capabilities, permissions, and modules.
Absence = denial.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    enabled: bool
    description: str


CAPABILITY_REGISTRY: Dict[str, RegistryEntry] = {
    "music_playback": RegistryEntry("music_playback", True, "Play/stop/next music locally or via Jellyfin."),
    "system_health": RegistryEntry("system_health", True, "Read-only system health reporting."),
    "rag_query": RegistryEntry("rag_query", True, "Read-only knowledge lookup."),
    "memory_write": RegistryEntry("memory_write", True, "Write durable memory on explicit request."),
}

PERMISSION_REGISTRY: Dict[str, RegistryEntry] = {
    "music_playback": RegistryEntry("music_playback", True, "User-approved music control."),
    "system_health": RegistryEntry("system_health", True, "Read-only system health queries."),
    "rag_query": RegistryEntry("rag_query", True, "Read-only RAG lookups."),
    "memory_write": RegistryEntry("memory_write", True, "User-approved memory writes."),
}

MODULE_REGISTRY: Dict[str, RegistryEntry] = {
    "music_player": RegistryEntry("music_player", True, "Music playback module."),
    "system_health": RegistryEntry("system_health", True, "System health module."),
    "rag": RegistryEntry("rag", True, "Local RAG index."),
    "memory": RegistryEntry("memory", True, "SQLite memory store."),
}


def is_capability_enabled(key: str) -> bool:
    entry = CAPABILITY_REGISTRY.get(key)
    return bool(entry and entry.enabled)


def is_permission_allowed(key: str) -> bool:
    entry = PERMISSION_REGISTRY.get(key)
    return bool(entry and entry.enabled)


def is_module_enabled(key: str) -> bool:
    entry = MODULE_REGISTRY.get(key)
    return bool(entry and entry.enabled)


def registries_snapshot() -> Tuple[Dict[str, RegistryEntry], Dict[str, RegistryEntry], Dict[str, RegistryEntry]]:
    return CAPABILITY_REGISTRY, PERMISSION_REGISTRY, MODULE_REGISTRY
