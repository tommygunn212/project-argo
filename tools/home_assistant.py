"""
ARGO Home Assistant Integration
─────────────────────────────────
Controls smart-home devices via the Home Assistant REST API.
Supports: lights, switches, climate (AC/heat), media players (TV/speakers),
covers (blinds/garage), fans, locks, and scenes.

Config in config.json:
{
    "home_assistant": {
        "url": "http://homeassistant.local:8123",
        "token": "YOUR_LONG_LIVED_ACCESS_TOKEN"
    }
}
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("argo.home_assistant")

# ── Config ────────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_ha_config() -> Dict:
    """Return the home_assistant block from config.json (or {})."""
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return data.get("home_assistant", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def is_home_assistant_configured() -> bool:
    cfg = _load_ha_config()
    return bool(cfg.get("url") and cfg.get("token"))


# ── HTTP helpers ──────────────────────────────────────────────────────

def _ha_request(method: str, path: str, body: Optional[dict] = None) -> dict:
    """Make an authenticated request to the Home Assistant REST API."""
    cfg = _load_ha_config()
    url = cfg.get("url", "").rstrip("/")
    token = cfg.get("token", "")
    if not url or not token:
        raise RuntimeError("Home Assistant not configured. Add home_assistant.url and home_assistant.token to config.json.")

    full_url = f"{url}/api/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(full_url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw}
    except HTTPError as e:
        logger.error(f"HA API error {e.code}: {e.reason}")
        raise RuntimeError(f"Home Assistant returned {e.code}: {e.reason}")
    except URLError as e:
        logger.error(f"HA connection error: {e.reason}")
        raise RuntimeError(f"Cannot reach Home Assistant: {e.reason}")


def _ha_post(path: str, body: Optional[dict] = None) -> dict:
    return _ha_request("POST", path, body)


def _ha_get(path: str) -> dict:
    return _ha_request("GET", path)


# ── Device discovery ──────────────────────────────────────────────────

DOMAIN_FRIENDLY = {
    "light": "light",
    "switch": "switch",
    "climate": "thermostat",
    "media_player": "media player",
    "fan": "fan",
    "cover": "cover",
    "lock": "lock",
    "scene": "scene",
    "automation": "automation",
}

# Domains we expose to voice control
CONTROLLABLE_DOMAINS = {"light", "switch", "climate", "media_player", "fan", "cover", "lock", "scene"}


def get_all_states() -> list:
    """Return all entity states from HA."""
    result = _ha_request("GET", "states")
    if isinstance(result, list):
        return result
    return result.get("raw", []) if isinstance(result, dict) else []


def get_entity_state(entity_id: str) -> dict:
    """Return state dict for one entity."""
    return _ha_request("GET", f"states/{entity_id}")


def list_devices(domain: Optional[str] = None) -> List[Dict]:
    """List controllable devices, optionally filtered by domain."""
    states = get_all_states()
    if not isinstance(states, list):
        return []
    devices = []
    for entity in states:
        eid = entity.get("entity_id", "")
        d = eid.split(".")[0] if "." in eid else ""
        if d not in CONTROLLABLE_DOMAINS:
            continue
        if domain and d != domain:
            continue
        friendly = entity.get("attributes", {}).get("friendly_name", eid)
        devices.append({
            "entity_id": eid,
            "domain": d,
            "name": friendly,
            "state": entity.get("state", "unknown"),
        })
    return devices


# ── Control actions ───────────────────────────────────────────────────

def turn_on(entity_id: str) -> str:
    """Turn on a device."""
    domain = entity_id.split(".")[0]
    _ha_post(f"services/{domain}/turn_on", {"entity_id": entity_id})
    friendly = _get_friendly_name(entity_id)
    return f"{friendly} turned on."


def turn_off(entity_id: str) -> str:
    """Turn off a device."""
    domain = entity_id.split(".")[0]
    _ha_post(f"services/{domain}/turn_off", {"entity_id": entity_id})
    friendly = _get_friendly_name(entity_id)
    return f"{friendly} turned off."


def toggle(entity_id: str) -> str:
    """Toggle a device."""
    domain = entity_id.split(".")[0]
    _ha_post(f"services/{domain}/toggle", {"entity_id": entity_id})
    friendly = _get_friendly_name(entity_id)
    return f"{friendly} toggled."


def set_brightness(entity_id: str, brightness_pct: int) -> str:
    """Set light brightness (0-100)."""
    brightness_pct = max(0, min(100, brightness_pct))
    brightness_val = int(brightness_pct * 255 / 100)
    _ha_post("services/light/turn_on", {
        "entity_id": entity_id,
        "brightness": brightness_val,
    })
    friendly = _get_friendly_name(entity_id)
    return f"{friendly} set to {brightness_pct}% brightness."


def set_color(entity_id: str, color_name: str) -> str:
    """Set light color by name."""
    colors = {
        "red": [255, 0, 0], "green": [0, 255, 0], "blue": [0, 0, 255],
        "white": [255, 255, 255], "warm white": [255, 200, 150],
        "yellow": [255, 255, 0], "purple": [128, 0, 128],
        "orange": [255, 165, 0], "pink": [255, 105, 180],
        "cyan": [0, 255, 255],
    }
    rgb = colors.get(color_name.lower())
    if not rgb:
        return f"Unknown color '{color_name}'. Try: {', '.join(colors.keys())}."
    _ha_post("services/light/turn_on", {
        "entity_id": entity_id,
        "rgb_color": rgb,
    })
    friendly = _get_friendly_name(entity_id)
    return f"{friendly} set to {color_name}."


def set_temperature(entity_id: str, temp: float, mode: Optional[str] = None) -> str:
    """Set thermostat temperature."""
    body = {"entity_id": entity_id, "temperature": temp}
    if mode:
        _ha_post("services/climate/set_hvac_mode", {"entity_id": entity_id, "hvac_mode": mode})
    _ha_post("services/climate/set_temperature", body)
    friendly = _get_friendly_name(entity_id)
    result = f"{friendly} set to {temp} degrees."
    if mode:
        result = f"{friendly} set to {mode} mode, {temp} degrees."
    return result


def activate_scene(entity_id: str) -> str:
    """Activate a Home Assistant scene."""
    _ha_post("services/scene/turn_on", {"entity_id": entity_id})
    friendly = _get_friendly_name(entity_id)
    return f"Scene '{friendly}' activated."


def lock_device(entity_id: str) -> str:
    _ha_post("services/lock/lock", {"entity_id": entity_id})
    return f"{_get_friendly_name(entity_id)} locked."


def unlock_device(entity_id: str) -> str:
    _ha_post("services/lock/unlock", {"entity_id": entity_id})
    return f"{_get_friendly_name(entity_id)} unlocked."


# ── Helpers ───────────────────────────────────────────────────────────

def _get_friendly_name(entity_id: str) -> str:
    """Get the friendly name for an entity, falling back to its ID."""
    try:
        state = get_entity_state(entity_id)
        return state.get("attributes", {}).get("friendly_name", entity_id)
    except Exception:
        return entity_id


def resolve_entity(name: str, domain: Optional[str] = None) -> Optional[str]:
    """
    Fuzzy-match a spoken device name to an entity_id.
    Returns the best matching entity_id or None.
    """
    name_lower = name.lower().strip()
    if not name_lower:
        return None

    devices = list_devices(domain)
    # Exact match on friendly name
    for d in devices:
        if d["name"].lower() == name_lower:
            return d["entity_id"]
    # Substring match
    for d in devices:
        if name_lower in d["name"].lower():
            return d["entity_id"]
    # Word overlap match
    name_words = set(name_lower.split())
    best, best_score = None, 0
    for d in devices:
        dev_words = set(d["name"].lower().split())
        overlap = len(name_words & dev_words)
        if overlap > best_score:
            best_score = overlap
            best = d["entity_id"]
    return best if best_score > 0 else None


# ── Voice command parser ──────────────────────────────────────────────

def parse_smart_home_command(text: str) -> Dict:
    """
    Parse a voice command into a smart-home action.

    Returns dict with keys:
        action: turn_on | turn_off | toggle | set_brightness | set_color |
                set_temperature | status | list_devices | activate_scene |
                lock | unlock
        device: spoken device name (e.g., "living room lights")
        domain: optional domain hint (light, switch, climate, etc.)
        value:  brightness %, temperature, color name, etc.
        mode:   HVAC mode (heat, cool, auto) for climate
    """
    text = (text or "").strip()
    lower = text.lower()
    result: Dict = {"action": None, "device": "", "domain": None, "value": None, "mode": None}

    # ── Scene activation ──
    m = re.search(r"\b(activate|set|trigger)\s+(the\s+)?(.+?)\s+scene\b", lower)
    if not m:
        m = re.search(r"\bscene\s+(.+)", lower)
    if m:
        scene_name = m.group(m.lastindex).strip()
        result["action"] = "activate_scene"
        result["device"] = scene_name
        result["domain"] = "scene"
        return result

    # ── Lock / unlock ──
    if re.search(r"\block\b", lower) and not re.search(r"\bunlock\b", lower):
        m = re.search(r"\block\s+(the\s+)?(.+)", lower)
        if m:
            result["action"] = "lock"
            result["device"] = m.group(2).strip()
            result["domain"] = "lock"
            return result

    if re.search(r"\bunlock\b", lower):
        m = re.search(r"\bunlock\s+(the\s+)?(.+)", lower)
        if m:
            result["action"] = "unlock"
            result["device"] = m.group(2).strip()
            result["domain"] = "lock"
            return result

    # ── Temperature / thermostat ──
    m = re.search(r"\bset\s+(the\s+)?(thermostat|ac|a\.?c|air\s*conditioning?|temperature|heat)\s+(?:to\s+)?(\d+)", lower)
    if m:
        result["action"] = "set_temperature"
        result["device"] = m.group(2).strip()
        result["domain"] = "climate"
        result["value"] = float(m.group(3))
        # Detect HVAC mode
        if re.search(r"\b(cool|cooling|ac|a\.?c|air\s*conditioning?)\b", lower):
            result["mode"] = "cool"
        elif re.search(r"\b(heat|heating|warm)\b", lower):
            result["mode"] = "heat"
        return result

    # ── Brightness ──
    m = re.search(r"\b(?:set|dim|brighten)\s+(the\s+)?(.+?)\s+(?:to\s+)?(\d+)\s*%?", lower)
    if m and re.search(r"\b(light|lamp|dim|bright)\b", lower):
        result["action"] = "set_brightness"
        result["device"] = m.group(2).strip()
        result["domain"] = "light"
        result["value"] = int(m.group(3))
        return result

    # ── Color ──
    m = re.search(r"\b(?:set|change|make)\s+(the\s+)?(.+?)\s+(?:to\s+)?(red|green|blue|white|warm\s*white|yellow|purple|orange|pink|cyan)\b", lower)
    if m:
        result["action"] = "set_color"
        result["device"] = m.group(2).strip()
        result["domain"] = "light"
        result["value"] = m.group(3).strip()
        return result

    # ── Status ──
    if re.search(r"\b(status|state|check)\b.*\b(light|lamp|switch|plug|fan|thermostat|ac|tv|lock|blind)\b", lower) or \
       re.search(r"\bis\s+(the\s+)?(.+?)\s+(on|off|open|closed|locked|unlocked)\b", lower):
        result["action"] = "status"
        # Extract device name
        m = re.search(r"\b(?:status|state|check)\s+(?:of\s+)?(?:the\s+)?(.+?)(?:\s+(?:status|state))?$", lower)
        if not m:
            m = re.search(r"\bis\s+(?:the\s+)?(.+?)\s+(?:on|off|open|closed|locked|unlocked)\b", lower)
        if m:
            result["device"] = m.group(1).strip()
        return result

    # ── List devices ──
    if re.search(r"\b(list|show|what)\b.*\b(devices?|lights?|switches?|smart\s*home|rooms?)\b", lower):
        result["action"] = "list_devices"
        if re.search(r"\blight", lower):
            result["domain"] = "light"
        elif re.search(r"\bswitch", lower):
            result["domain"] = "switch"
        return result

    # ── Turn on / off / toggle ──
    m = re.search(r"\bturn\s+(on|off)\s+(the\s+)?(.+)", lower)
    if m:
        result["action"] = "turn_on" if m.group(1) == "on" else "turn_off"
        result["device"] = m.group(3).strip()
        _infer_domain(result)
        return result

    # "switch on/off the X"
    m = re.search(r"\bswitch\s+(on|off)\s+(the\s+)?(.+)", lower)
    if m:
        result["action"] = "turn_on" if m.group(1) == "on" else "turn_off"
        result["device"] = m.group(3).strip()
        _infer_domain(result)
        return result

    # "{device} on/off"
    m = re.search(r"^(.+?)\s+(on|off)$", lower)
    if m:
        result["action"] = "turn_on" if m.group(2) == "on" else "turn_off"
        result["device"] = m.group(1).strip()
        _infer_domain(result)
        return result

    # "toggle the X"
    m = re.search(r"\btoggle\s+(the\s+)?(.+)", lower)
    if m:
        result["action"] = "toggle"
        result["device"] = m.group(2).strip()
        _infer_domain(result)
        return result

    return result


def _infer_domain(result: Dict) -> None:
    """Infer domain from device name keywords."""
    dev = result.get("device", "").lower()
    if any(w in dev for w in ("light", "lamp", "bulb", "strip")):
        result["domain"] = "light"
    elif any(w in dev for w in ("tv", "television", "roku", "chromecast", "speaker", "receiver")):
        result["domain"] = "media_player"
    elif any(w in dev for w in ("thermostat", "ac", "a/c", "heat", "climate")):
        result["domain"] = "climate"
    elif any(w in dev for w in ("fan",)):
        result["domain"] = "fan"
    elif any(w in dev for w in ("lock", "deadbolt")):
        result["domain"] = "lock"
    elif any(w in dev for w in ("blind", "shade", "curtain", "garage")):
        result["domain"] = "cover"


def execute_smart_home_command(text: str) -> str:
    """
    Parse and execute a smart-home voice command.
    Returns a spoken response string.
    """
    if not is_home_assistant_configured():
        return "Home Assistant is not configured. Add your URL and access token to config.json under home_assistant."

    parsed = parse_smart_home_command(text)
    action = parsed.get("action")

    if not action:
        return "I didn't understand the smart home command. Try something like 'turn on the living room lights' or 'set thermostat to 72'."

    if action == "list_devices":
        devices = list_devices(parsed.get("domain"))
        if not devices:
            return "No smart home devices found."
        names = [f"{d['name']} ({d['state']})" for d in devices[:10]]
        return f"Found {len(devices)} devices. " + ", ".join(names) + "."

    if action == "status":
        device_name = parsed.get("device", "")
        entity_id = resolve_entity(device_name)
        if not entity_id:
            return f"I couldn't find a device called '{device_name}'."
        state = get_entity_state(entity_id)
        friendly = state.get("attributes", {}).get("friendly_name", entity_id)
        current = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        info = f"{friendly} is {current}."
        if "current_temperature" in attrs:
            info += f" Temperature is {attrs['current_temperature']} degrees."
        if "brightness" in attrs:
            pct = int(attrs["brightness"] * 100 / 255)
            info += f" Brightness is {pct}%."
        return info

    if action == "activate_scene":
        scene_name = parsed.get("device", "")
        entity_id = resolve_entity(scene_name, "scene")
        if not entity_id:
            return f"I couldn't find a scene called '{scene_name}'."
        return activate_scene(entity_id)

    if action in ("lock", "unlock"):
        device_name = parsed.get("device", "")
        entity_id = resolve_entity(device_name, "lock")
        if not entity_id:
            return f"I couldn't find a lock called '{device_name}'."
        return lock_device(entity_id) if action == "lock" else unlock_device(entity_id)

    if action == "set_temperature":
        device_name = parsed.get("device", "")
        entity_id = resolve_entity(device_name, "climate") or resolve_entity("thermostat", "climate")
        if not entity_id:
            return "I couldn't find a thermostat. Check your Home Assistant devices."
        return set_temperature(entity_id, parsed["value"], parsed.get("mode"))

    if action == "set_brightness":
        device_name = parsed.get("device", "")
        entity_id = resolve_entity(device_name, "light")
        if not entity_id:
            return f"I couldn't find a light called '{device_name}'."
        return set_brightness(entity_id, parsed["value"])

    if action == "set_color":
        device_name = parsed.get("device", "")
        entity_id = resolve_entity(device_name, "light")
        if not entity_id:
            return f"I couldn't find a light called '{device_name}'."
        return set_color(entity_id, parsed["value"])

    # turn_on / turn_off / toggle
    device_name = parsed.get("device", "")
    entity_id = resolve_entity(device_name, parsed.get("domain"))
    if not entity_id:
        return f"I couldn't find a device called '{device_name}'."

    if action == "turn_on":
        return turn_on(entity_id)
    elif action == "turn_off":
        return turn_off(entity_id)
    elif action == "toggle":
        return toggle(entity_id)

    return "I'm not sure how to handle that smart home command."
