"""
Policy Module (Centralized Timeouts & Retries)

Constants only. No side effects. No imports from other ARGO modules.
"""

# LLM timeouts and retry policy
LLM_TIMEOUT_SECONDS = 30
LLM_RETRIES = 1
LLM_BACKOFF_SECONDS = 0.5

# Fast-path (deterministic command) timeout budget
FAST_PATH_TIMEOUT_SECONDS = 2

# LLM extraction (music metadata) timeout
LLM_EXTRACT_TIMEOUT_SECONDS = 3

# TTS timeouts
TTS_TIMEOUT_SECONDS = 10

# Audio playback timeouts
AUDIO_PLAYBACK_TIMEOUT_SECONDS = 3600
AUDIO_STOP_TIMEOUT_SECONDS = 2

# Watchdog thresholds (values only)
LLM_WATCHDOG_SECONDS = 35
TTS_WATCHDOG_SECONDS = 12
AUDIO_WATCHDOG_SECONDS = 20
RESPONSE_WATCHDOG_SECONDS = 40

# Fallback response when watchdogs trigger (short, neutral)
WATCHDOG_FALLBACK_RESPONSE = "I'm having trouble right now."
