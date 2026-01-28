"""
Configuration Loader for ARGO

Reads from config.json and provides a simple interface for accessing settings.
Defaults to sensible values if config.json is missing (for backward compatibility).

Usage:
    from core.config import get_config
    config = get_config()
    music_path = config.get("music.library_path")
"""

import json
import os
import logging
import hashlib
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Feature flags
ENABLE_LLM_TTS_STREAMING = True
REQUIRE_LLM = False
MUSIC_DB_PATH = "data/music.db"
AUTO_INIT_DB = False


class Config:
    """Simple config wrapper with dot-notation access."""
    
    def __init__(self, data: dict):
        """Initialize with config dict."""
        self._data = data
        self._hash = config_hash(self._data)
    
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
    
    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access."""
        return self.get(key)

    @property
    def hash(self) -> str:
        return self._hash


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
        "device": "cpu"
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
    }
}

_config_instance: Optional[Config] = None

# Runtime overrides (non-persistent)
_RUNTIME_OVERRIDES_DEFAULT = {
    "barge_in_enabled": True,
    "tts_enabled": True,
    "music_enabled": True,
    "debug_level": "INFO",
    "personality_mode": "tommy_gunn",
}
_runtime_overrides = dict(_RUNTIME_OVERRIDES_DEFAULT)


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
