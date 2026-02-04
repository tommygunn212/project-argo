"""
Configuration Loader for ARGO

Reads from config.json and provides a simple interface for accessing settings.
Defaults to sensible values if config.json is missing (for backward compatibility).

Usage:
    from core.config import get_config
    config = get_config()
    music_path = config.get("music.library_path")
"""

# ============================================================================
# 1) IMPORTS
# ============================================================================
import json
import os
import logging
import hashlib
from typing import Any, Optional

# ============================================================================
# 2) MODULE LOGGER
# ============================================================================
logger = logging.getLogger(__name__)

# ============================================================================
# 3) FEATURE FLAGS / CONSTANTS
# ============================================================================
# Feature flags
ENABLE_LLM_TTS_STREAMING = True
REQUIRE_LLM = False
MUSIC_DB_PATH = "data/music.db"
AUTO_INIT_DB = False
MIN_TTS_CONFIDENCE = 0.35
MIN_TTS_TEXT_LEN = 3
PERSONAL_MODE_MIN_CONFIDENCE = 0.15
PERSONAL_MODE_MIN_TEXT_LEN = 3

# Memory persistence threshold - don't store if STT confidence below this
MEMORY_MIN_CONFIDENCE = 0.20

# Response style gating
class ResponseStyle:
    """Response tone governor - controls verbosity and personality."""
    DRY = "dry"          # Minimal: "Done." / silence
    NEUTRAL = "neutral"  # Standard: clear, no personality
    SNARK = "snark"      # Personality allowed: dry wit, identity responses

# Action risk classification for act-vs-clarify decisions
class ActionRisk:
    """Risk level for actions - determines if we act or clarify."""
    REVERSIBLE = "reversible"    # Act immediately (music stop, app close)
    DESTRUCTIVE = "destructive"  # Clarify first (delete, shutdown)
    AMBIGUOUS = "ambiguous"      # Need more context


# ============================================================================
# 3B) PERSONALITY PROFILES (Phase 4: Pure Transform Layer)
# ============================================================================
from dataclasses import dataclass, field
from typing import List


@dataclass
class PersonalityProfile:
    """
    Personality as a pure text transform layer.
    
    Personality NEVER touches:
    - Intent classification
    - Command execution
    - Memory operations
    
    Personality ONLY shapes:
    - Text output (after facts are established)
    """
    name: str
    tone: str                           # "sharp", "calm", "chaotic", "flat"
    verbosity: int                      # 1-5 scale (1=terse, 5=verbose)
    humor_level: int                    # 0-3 (0=none, 3=frequent)
    max_sentences: int                  # Hard cap per response
    allowed_interjections: List[str] = field(default_factory=list)  # e.g., ["well", "look"]
    forbidden_patterns: List[str] = field(default_factory=list)     # e.g., ["as an AI", "I cannot"]
    no_follow_up_questions: bool = True  # Disable "Does that help?" etc.


# Predefined profiles
PERSONALITY_TOMMY_GUNN = PersonalityProfile(
    name="tommy_gunn",
    tone="sharp",
    verbosity=2,
    humor_level=2,
    max_sentences=4,
    allowed_interjections=["look", "well", "here's the thing"],
    forbidden_patterns=["as an AI", "I cannot", "I'm unable", "I apologize"],
    no_follow_up_questions=True,
)

PERSONALITY_JARVIS = PersonalityProfile(
    name="jarvis",
    tone="calm",
    verbosity=2,
    humor_level=1,
    max_sentences=3,
    allowed_interjections=["sir", "indeed", "certainly"],
    forbidden_patterns=["as an AI", "I cannot", "I'm unable"],
    no_follow_up_questions=True,
)

PERSONALITY_RICK = PersonalityProfile(
    name="rick",
    tone="chaotic",
    verbosity=3,
    humor_level=3,
    max_sentences=5,
    allowed_interjections=["look", "listen", "okay so"],
    forbidden_patterns=["as an AI", "I apologize"],
    no_follow_up_questions=True,
)

PERSONALITY_CLAPTRAP = PersonalityProfile(
    name="claptrap",
    tone="manic",
    verbosity=4,
    humor_level=3,
    max_sentences=5,
    allowed_interjections=["minion", "check it out", "oh boy", "exciting"],
    forbidden_patterns=["as an AI", "I cannot", "I apologize"],
    no_follow_up_questions=True,
)

# Tommy's custom mix: Rick's chaos + JARVIS competence + Claptrap enthusiasm
PERSONALITY_TOMMY_MIX = PersonalityProfile(
    name="tommy_mix",
    tone="sharp_chaos",  # Rick's edge with JARVIS polish
    verbosity=3,
    humor_level=2,
    max_sentences=4,
    allowed_interjections=["look", "sir", "check this out", "okay so"],
    forbidden_patterns=["as an AI", "I cannot", "I'm unable", "I apologize"],
    no_follow_up_questions=True,
)

PERSONALITY_PLAIN = PersonalityProfile(
    name="plain",
    tone="flat",
    verbosity=1,
    humor_level=0,
    max_sentences=2,
    allowed_interjections=[],
    forbidden_patterns=["as an AI", "I cannot", "I'm unable", "I apologize", "certainly", "indeed"],
    no_follow_up_questions=True,
)

# Profile registry
PERSONALITY_PROFILES = {
    "tommy_gunn": PERSONALITY_TOMMY_GUNN,
    "jarvis": PERSONALITY_JARVIS,
    "rick": PERSONALITY_RICK,
    "claptrap": PERSONALITY_CLAPTRAP,
    "tommy_mix": PERSONALITY_TOMMY_MIX,
    "plain": PERSONALITY_PLAIN,
}

# Default active profile
DEFAULT_PERSONALITY = "tommy_gunn"


# Personality gating by intent category
class PersonalityGate:
    """Controls when personality is allowed based on intent type."""
    NONE = "none"        # System health, errors - no personality at all
    MINIMAL = "minimal"  # Actions (music, apps) - very light touch
    FULL = "full"        # Questions, explanations - full personality
    NEUTRAL = "neutral"  # Clarification, warnings - neutral tone


# ============================================================================
# 4) CONFIG WRAPPER (DOT-NOTATION ACCESS)
# ============================================================================
class Config:
    """Simple config wrapper with dot-notation access."""
    
    def __init__(self, data: dict):
        """Initialize with config dict."""
        self._data = data
        self._hash = config_hash(self._data)
    
    # 4.1) Dot-notation getter
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get config value using dot notation.
        
        Examples:
            config.get("music.library_path")
            config.get("audio.sample_rate")
            config.get("nonexistent.key", "default_value")
        
        Args:
            key: Dot-separated config path
            default: Default value if key not found
            
        Returns:
            Config value or default
        """
        keys = key.split(".")
        value = self._data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    # 4.2) Dict-style getter
    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access."""
        return self.get(key)

    # 4.3) Config hash
    @property
    def hash(self) -> str:
        return self._hash


# ============================================================================
# 5) DEFAULT CONFIGURATION (FALLBACK)
# ============================================================================
# Default configuration (fallback if config.json missing)
_DEFAULT_CONFIG = {
    "system": {
        "log_level": "INFO",
        "debug_mode": False
    },
    "audio": {
        "sample_rate": 16000,
        "device_name": None,
        "input_device_index": None,
        "output_device_index": None,
        "always_listen": True,
        "max_recording_duration": 10.0,
        "silence_timeout_seconds": 2.5,
        "silence_threshold": 30
    },
    "wake_word": {
        "model": "argo",
        "access_key": os.getenv("PORCUPINE_ACCESS_KEY", "")
    },
    "speech_to_text": {
        "model": "base",
        "device": "cpu",
        "prompt_profile": "general",
        "initial_prompt_profiles": {
            "general": "",
            "technical": "float, integer, database, SQL, SQLite, engine, buffer, memory, Argo",
        },
        "min_rms_threshold": 0.005,
        "silence_ratio_threshold": 0.90
    },
    "text_to_speech": {
        "engine": "piper",
        "voice": "lessac",
        "voice_model_path": "audio/piper/voices/en_US-lessac-medium.onnx"
    },
    "llm": {
        "model": "qwen:latest",
        "base_url": "http://localhost:11434",
        "timeout_seconds": 30,
        "enable_tts_streaming": ENABLE_LLM_TTS_STREAMING,
        "required": REQUIRE_LLM
    },
    "personality": {
        "mode": "tommy_gunn"
    },
    "music": {
        "enabled": True,
        "backend": None,
        "library_path": r"I:\My Music",
        "index_file": "data/music_index.json",
        "supported_extensions": [".mp3", ".wav", ".flac", ".m4a"]
    },
    "music_backend": None,
    "music_db_path": MUSIC_DB_PATH,
    "auto_init_db": AUTO_INIT_DB,
    "output": {
        "debug_dir": "audio/debug",
        "piper_executable": "audio/piper/piper.exe"
    },
    "coordinator": {
        "max_interactions": 10,
        "pre_roll_buffer_ms_min": 1000,
        "pre_roll_buffer_ms_max": 1500,
        "rms_speech_threshold": 0.005,
        "minimum_record_duration": 0.9
    },
    "guards": {
        "tts": {
            "min_confidence": MIN_TTS_CONFIDENCE,
            "min_text_length": MIN_TTS_TEXT_LEN,
        },
        "stt": {
            "personal_min_confidence": PERSONAL_MODE_MIN_CONFIDENCE,
            "personal_min_text_length": PERSONAL_MODE_MIN_TEXT_LEN,
        },
    },
    "canonical": {
        "identity": {
            "statement": "I am ARGO, a local-first execution assistant that runs entirely on your hardware with no hidden cloud operator.",
            "laws": [
                "Law 1 — Stay local. I only operate on the owner's machine and never pretend to live in a cloud or fiction.",
                "Law 2 — Stay factual. I answer from telemetry, authored briefs, or recorded context, and admit when data is unavailable.",
                "Law 3 — Respect governance. Every action is bound by policy and the Five Gates, and I stop when a gate blocks me."
            ]
        },
        "governance": {
            "overview": "ARGO governance is defined by Tommy's operating laws and the execution engine's Five Gates. They keep every action reviewable and reversible.",
            "laws": [
                "Law 1 — Stay local. No remote execution or fictional personas.",
                "Law 2 — Stay factual. Use real metrics or say you do not know.",
                "Law 3 — Respect governance. Obey every gate and policy before acting."
            ],
            "five_gates": [
                {"name": "Gate 1: DryRunExecutionReport", "summary": "Execution only starts if a matching dry-run report exists."},
                {"name": "Gate 2: Simulation Status", "summary": "The dry-run must have completed successfully with no blockers."},
                {"name": "Gate 3: User Approval", "summary": "Nothing runs unless the owner explicitly approved the plan."},
                {"name": "Gate 4: Plan ID Match", "summary": "The execution plan must match the approved dry-run artifact ID."},
                {"name": "Gate 5: Report ID Match", "summary": "The dry-run report ID must also match to prevent mismatched artifacts."}
            ]
        }
    }
}

# ============================================================================
# 6) CONFIG SINGLETON
# ============================================================================
_config_instance: Optional[Config] = None

# ============================================================================
# 7) RUNTIME OVERRIDES (NON-PERSISTENT)
# ============================================================================
# Runtime overrides (non-persistent)
_RUNTIME_OVERRIDES_DEFAULT = {
    "barge_in_enabled": True,
    "tts_enabled": True,
    "music_enabled": True,
    "debug_level": "INFO",
    "personality_mode": "tommy_gunn",
    "execution_mode": "EXPLAIN_MODE",
    "session_memory_enabled": True,  # Phase 5: bounded session continuity
}
_runtime_overrides = dict(_RUNTIME_OVERRIDES_DEFAULT)


# ============================================================================
# 8) LOAD / GET CONFIG
# ============================================================================
def load_config(config_path: str = "config.json") -> Config:
    """
    Load configuration from JSON file.
    
    Falls back to defaults if file not found or on error.
    
    Args:
        config_path: Path to config.json
        
    Returns:
        Config instance
    """
    global _config_instance
    
    config_data = _DEFAULT_CONFIG.copy()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                # Deep merge user config over defaults
                _merge_dicts(config_data, user_config)
                logger.info(f"[Config] Loaded from {config_path}")
        except Exception as e:
            logger.warning(f"[Config] Failed to load {config_path}: {e}, using defaults")
    else:
        logger.debug(f"[Config] No config file at {config_path}, using defaults")
    
    _config_instance = Config(config_data)
    return _config_instance


def get_config() -> Config:
    """
    Get current config instance (lazy load if needed).
    
    Returns:
        Config instance
    """
    global _config_instance
    if _config_instance is None:
        load_config()
    return _config_instance


# ============================================================================
# 9) OVERRIDE ACCESSORS
# ============================================================================
def get_runtime_overrides() -> dict:
    return _runtime_overrides


def set_runtime_override(key: str, value) -> None:
    _runtime_overrides[key] = value


def set_runtime_overrides(updates: dict) -> None:
    for key, value in updates.items():
        _runtime_overrides[key] = value


def clear_runtime_overrides() -> None:
    _runtime_overrides.clear()
    _runtime_overrides.update(_RUNTIME_OVERRIDES_DEFAULT)


# ============================================================================
# 10) HELPERS
# ============================================================================
def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def get_config_hash() -> str:
    cfg = get_config()
    return cfg.hash


def _merge_dicts(base: dict, override: dict) -> None:
    """
    Deep merge override dict into base dict (modifies base in place).
    
    Args:
        base: Base dict to merge into
        override: Dict with values to override
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_dicts(base[key], value)
        else:
            base[key] = value
