"""Pure parsing for explicit and implicit memory-write requests."""

from __future__ import annotations

import re


def parse_memory_write(user_text: str) -> dict | None:
    """Parse one memory write without reading or mutating pipeline state."""
    text = user_text.strip()
    original_lower = text.lower()
    lower = original_lower

    implicit_name = re.search(r"^my name is\s+([a-zA-Z][a-zA-Z\s'-]*)\.?$", lower)
    if implicit_name:
        name_value = implicit_name.group(1).strip().title()
        return {
            "type": "FACT",
            "key": "user.name",
            "value": name_value,
            "display": f"My name is {name_value}",
            "implicit": True,
        }

    implicit_call_me = re.search(r"^call me\s+([a-zA-Z][a-zA-Z\s'-]*)\.?$", lower)
    if implicit_call_me:
        name_value = implicit_call_me.group(1).strip().title()
        return {
            "type": "FACT",
            "key": "user.name",
            "value": name_value,
            "display": f"Call me {name_value}",
            "implicit": True,
        }

    implicit_preference = re.search(r"^i\s+(?:prefer|like)\s+(.+?)(?:\.|!|\?|$)", lower)
    if implicit_preference:
        preference_value = implicit_preference.group(1).strip(" ,.-")
        if preference_value and 2 <= len(preference_value) <= 180:
            return {
                "type": "PREFERENCE",
                "key": "user.preference",
                "value": preference_value,
                "display": f"I prefer {preference_value}",
                "implicit": True,
            }

    match = re.search(
        r"\b(remember that|remember this|remember|save this|don't forget|dont forget|store this|add this to memory)\b",
        lower,
    )
    if not match:
        return None

    text = text[match.start():]
    lower = text.lower()
    if re.search(r"\bremember\s+everything\b", lower) or (
        re.search(r"\bfrom now on\b", lower)
        and "remember" in lower
        and "everything" in lower
    ):
        return {"reject": "bulk"}

    mem_type = "FACT"
    if re.search(r"\b(project|this project)\b", original_lower):
        mem_type = "PROJECT"
    if re.search(r"\b(preference|prefer)\b", original_lower):
        mem_type = "PREFERENCE"

    remainder = re.sub(
        r"^(please\s+)?(remember|save this|from now on)\b",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" :,-")
    if not remainder:
        return {"type": mem_type, "key": None, "value": None}

    if mem_type == "EPHEMERAL":
        remainder = re.sub(
            r"^(for\s+this\s+session|this\s+session)\b",
            "",
            remainder,
            flags=re.IGNORECASE,
        ).strip(" :,-")

    like_match = re.search(r"^that\s+i\s+(like|love)\s+(.+)$", remainder, flags=re.IGNORECASE)
    if like_match:
        return {
            "type": mem_type,
            "key": "user.likes",
            "value": like_match.group(2).strip(),
            "display": f"I {like_match.group(1)} {like_match.group(2).strip()}",
        }

    call_match = re.search(r"\bcall me\s+(.+)$", remainder, flags=re.IGNORECASE)
    if call_match:
        return {
            "type": mem_type,
            "key": "user.name",
            "value": call_match.group(1).strip(),
            "display": f"My name is {call_match.group(1).strip()}",
        }

    name_match = re.search(r"\bmy name is\s+(.+)$", remainder, flags=re.IGNORECASE)
    if name_match:
        return {
            "type": mem_type,
            "key": "user.name",
            "value": name_match.group(1).strip(),
            "display": f"My name is {name_match.group(1).strip()}",
        }

    if ":" in remainder:
        key, value = remainder.split(":", 1)
        return {
            "type": mem_type,
            "key": key.strip(" .,!?:;"),
            "value": value.strip(),
            "display": remainder.strip(),
        }
    if " is " in remainder:
        key, value = remainder.split(" is ", 1)
        return {
            "type": mem_type,
            "key": key.strip(" .,!?:;"),
            "value": value.strip(),
            "display": remainder.strip(),
        }
    return {
        "type": mem_type,
        "key": None,
        "value": remainder.strip(),
        "display": remainder.strip(),
    }
