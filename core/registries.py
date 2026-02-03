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
    "audio_routing_control": RegistryEntry("audio_routing_control", True, "Audio routing control."),
    "app_control": RegistryEntry("app_control", True, "Application launch/control."),
    "app_focus_control": RegistryEntry("app_focus_control", True, "Application focus control."),
    "app_launch": RegistryEntry("app_launch", True, "Tier-1 application launch."),
    "bluetooth_control": RegistryEntry("bluetooth_control", True, "Bluetooth adapter/device control."),
    "system_volume": RegistryEntry("system_volume", True, "System master volume status/control."),
    "rag_query": RegistryEntry("rag_query", True, "Read-only knowledge lookup."),
    "memory_write": RegistryEntry("memory_write", True, "Write durable memory on explicit request."),
}

PERMISSION_REGISTRY: Dict[str, RegistryEntry] = {
    "music_playback": RegistryEntry("music_playback", True, "User-approved music control."),
    "system_health": RegistryEntry("system_health", True, "Read-only system health queries."),
    "audio_routing_control": RegistryEntry("audio_routing_control", True, "User-approved audio routing control."),
    "app_control": RegistryEntry("app_control", True, "User-approved app control."),
    "app_focus_control": RegistryEntry("app_focus_control", True, "User-approved app focus control."),
    "app_launch": RegistryEntry("app_launch", True, "User-approved tier-1 app launch."),
    "bluetooth_control": RegistryEntry("bluetooth_control", True, "User-approved bluetooth control."),
    "system_volume": RegistryEntry("system_volume", True, "User-approved system volume control."),
    "rag_query": RegistryEntry("rag_query", True, "Read-only RAG lookups."),
    "memory_write": RegistryEntry("memory_write", True, "User-approved memory writes."),
}

MODULE_REGISTRY: Dict[str, RegistryEntry] = {
    "music_player": RegistryEntry("music_player", True, "Music playback module."),
    "system_health": RegistryEntry("system_health", True, "System health module."),
    "audio_routing": RegistryEntry("audio_routing", True, "Audio routing module."),
    "app_control": RegistryEntry("app_control", True, "Application control module."),
    "app_focus": RegistryEntry("app_focus", True, "Application focus module."),
    "app_launch": RegistryEntry("app_launch", True, "Tier-1 app launch module."),
    "bluetooth": RegistryEntry("bluetooth", True, "Bluetooth status/control module."),
    "system_volume": RegistryEntry("system_volume", True, "System volume module."),
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
