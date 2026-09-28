"""Deterministic canonical-topic classification for the classic pipeline."""

from __future__ import annotations

import re

from core.intent_parser import (
    HARDWARE_KEYWORDS,
    SYSTEM_CPU_QUERIES,
    SYSTEM_GPU_QUERIES,
    SYSTEM_MEMORY_QUERIES,
    SYSTEM_MOTHERBOARD_QUERIES,
    SYSTEM_OS_QUERIES,
    detect_disk_query,
    detect_system_health,
    detect_temperature_query,
)


def classify_canonical_topic(user_text):
    """
    Deterministically classify user_text into canonical topic buckets.
    Returns (topic, matched_keywords) or (None, set())
    """
    text = user_text.lower() if user_text else ""
    tokens = set(re.findall(r"\w+", text))
    phrases = text

    identity_phrases = {
        "what cpu do i have",
        "which cpu",
        "cpu brand",
        "cpu model",
        "what processor do i have",
        "which processor",
        "processor model",
        "processor name",
        "what gpu do i have",
        "which gpu",
        "gpu brand",
        "gpu model",
        "what graphics card",
        "what video card",
        "what motherboard",
        "which motherboard",
        "motherboard brand",
        "motherboard model",
        "what os",
        "what operating system",
        "os version",
        "system specs",
        "hardware specs",
    }
    qualifier_tokens = {"brand", "model", "type"}
    hardware_tokens = {"cpu", "processor", "gpu", "graphics", "video", "motherboard", "ram", "memory", "os"}
    identity_query = any(p in phrases for p in identity_phrases) or (
        (tokens & qualifier_tokens) and (tokens & hardware_tokens)
    )

    # SYSTEM_HEALTH short-circuit (must be evaluated before SELF_IDENTITY)
    # Guard: skip if question is general knowledge (shopping, building, 3D printing, recommendations)
    _general_knowledge_guard = re.search(
        r"\b(latest|best|newest|buy|buying|recommend|build|building|upgrade|upgrading"
        r"|compare|comparing|vs|versus|review|benchmark|shop|shopping|market|available"
        r"|released|announcement|generation|lineup|should\s+i\s+get|worth|price|cost"
        r"|hotend|printer|3d|filament|nozzle|extruder)\b",
        text,
    )
    health_matches = set()
    if not _general_knowledge_guard:
        if detect_system_health(text):
            health_matches.add("system_health")
        if detect_disk_query(text):
            health_matches.add("disk")
        if detect_temperature_query(text):
            health_matches.add("temperature")
        for kw in HARDWARE_KEYWORDS:
            if kw in text:
                health_matches.add(kw)
        for q in SYSTEM_OS_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MEMORY_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_CPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_GPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MOTHERBOARD_QUERIES:
            if q in text:
                health_matches.add(q)
        if tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"}:
            health_matches |= (tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"})
    if health_matches and not identity_query:
        return "SYSTEM_HEALTH", health_matches

    # COUNT short-circuit (numeric/utility before other canonical topics)
    count_number_tokens = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
    }
    if ("count" in tokens and ("to" in tokens or tokens & count_number_tokens or re.search(r"\b\d+\b", text))):
        return "COUNT", {"count"}
    governance_phrases = {
        "argo laws",
        "the laws",
        "governing laws",
        "five gates",
        "hard gates",
        "permission gates",
        "argo gates",
    }
    matched_governance_phrases = {p for p in governance_phrases if p in phrases}
    if matched_governance_phrases:
        return "ARGO_GOVERNANCE", matched_governance_phrases
    governance_keywords = {
        "law",
        "laws",
        "rule",
        "rules",
        "constraint",
        "constraints",
        "policy",
        "policies",
        "gate",
        "gates",
        "permission",
        "permissions",
        "govern",
        "governing",
    }
    matched_governance_keywords = tokens & governance_keywords
    if matched_governance_keywords:
        return "ARGO_GOVERNANCE", matched_governance_keywords

    topic_keywords = {
        # Removed 'system' from ARCHITECTURE keywords to allow 'system health' etc. to route to normal logic
        "ARCHITECTURE": {"architecture", "design", "pipeline", "structure", "modules", "components", "layout", "engine"},
    }
    topic_phrases = {
        "ARCHITECTURE": {"system architecture", "pipeline design", "argo architecture"},
    }
    for topic in ["ARCHITECTURE"]:
        phrases_for_topic = topic_phrases.get(topic, set())
        matched_phrases = {p for p in phrases_for_topic if p in phrases}
        if matched_phrases:
            return topic, matched_phrases
        keywords = topic_keywords[topic]
        matched = tokens & keywords
        if matched:
            return topic, matched

    # CODEBASE_STATS explicit phrase matching only (avoid count-only triggers)
    codebase_phrases = {
        "codebase",
        "code base",
        "codebase stats",
        "repo stats",
        "repository stats",
        "workspace stats",
        "project stats",
        "workspace size",
        "repo size",
        "repository size",
        "lines of code",
        "python files",
        "file count",
        "files in workspace",
        "files in the workspace",
    }
    matched_codebase = {p for p in codebase_phrases if p in text}
    if matched_codebase:
        return "CODEBASE_STATS", matched_codebase

    # CAPABILITIES before SELF_IDENTITY fallback
    capabilities_phrases = {
        "what can you do",
        "what can argo do",
        "what can you do for me",
        "what are your capabilities",
        "what are your features",
        "list your capabilities",
        "list your features",
    }
    if any(p in phrases for p in capabilities_phrases):
        return "CAPABILITIES", {p for p in capabilities_phrases if p in phrases}

    # ARGO_IDENTITY fallback (tightened)
    keywords = {"identity", "yourself", "argo", "agent", "assistant", "name"}
    matched = tokens & keywords
    identity_phrases = {
        "who are you",
        "what are you",
        "who is argo",
        "what is argo",
        "what is your name",
        "what's your name",
        "whats your name",
        "tell me about yourself",
        "tell me about you",
        "identify yourself",
        "who am i talking to",
        "who am i speaking to",
    }
    # Word-boundary match to avoid false positives like "tell me about your feet"
    matched_phrases = set()
    for p in identity_phrases:
        # Pattern: phrase must be at word boundary (not followed by more words that change meaning)
        # "tell me about you" should NOT match "tell me about your feet"
        pattern = re.escape(p) + r"(?:[.!?\s]|$)"
        if re.search(pattern, text, re.IGNORECASE):
            matched_phrases.add(p)
    if matched_phrases:
        return "ARGO_IDENTITY", matched_phrases
    identity_specific = tokens & {"argo", "yourself", "identity"}
    question_cue = tokens & {"who", "what"}
    if identity_specific and question_cue:
        return "ARGO_IDENTITY", (identity_specific | question_cue)
    return None, set()

