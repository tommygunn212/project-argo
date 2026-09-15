"""GE SmartHQ air conditioners for ARGO.

Credentials are read only from the environment or .env. They are never accepted
as arguments, never returned, and are scrubbed from every log line, result and
exception this module can produce.

The SmartHQ transport is an event-driven websocket: connecting gives you a list
of appliances, and each one reports its type and ERD values as they arrive. This
module wraps that into plain request/response calls that connect, do one job and
disconnect, so a wedged socket can never hold the voice worker open.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("ARGO.SmartHome")

ENV_USER = "GE_SMARTHQ_USERNAME"
ENV_PASS = "GE_SMARTHQ_PASSWORD"
ENV_REGION = "GE_SMARTHQ_REGION"

ARGO_ROOT = Path(__file__).resolve().parent.parent
DOTENV = ARGO_ROOT / ".env"

# Every GE appliance type that is an air conditioner. AIR_HANDLER_VRF is
# deliberately excluded: it is a whole-home air handler, not a room unit.
AC_TYPE_NAMES = {
    "AIR_CONDITIONER",
    "SPLIT_AIR_CONDITIONER",
    "PORTABLE_AIR_CONDITIONER",
    "BUILT_IN_AIR_CONDITIONER",
}

CONNECT_TIMEOUT = 45.0
SETTLE_SECONDS = 6.0

_SECRETS: set[str] = set()


def _remember_secret(value: str) -> None:
    """Track a value so it can be scrubbed from anything we emit."""
    if value and len(value) >= 4:
        _SECRETS.add(value)


def redact(text: Any) -> str:
    """Return text with every known credential replaced by a placeholder."""
    out = str(text)
    for secret in _SECRETS:
        if secret and secret in out:
            out = out.replace(secret, "<redacted>")
    # Belt and braces: scrub anything that looks like a bearer token.
    out = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}", r"\1<redacted>", out)
    return out


class SmartHomeError(RuntimeError):
    """A SmartHQ failure whose message is already redacted."""


def _dotenv_lookup(name: str) -> Optional[str]:
    """Read one key from .env without requiring python-dotenv."""
    try:
        if not DOTENV.is_file():
            return None
        for raw in DOTENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() != name:
                continue
            value = value.strip().strip('"').strip("'")
            return value or None
    except Exception:
        logger.debug("[SmartHome] could not read .env", exc_info=True)
    return None


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return _dotenv_lookup(name)


def credentials_present() -> bool:
    """True when both SmartHQ credentials can be resolved. Reveals nothing."""
    return bool(_env(ENV_USER)) and bool(_env(ENV_PASS))


def credential_status() -> dict:
    """A safe description of credential state for the UI and logs."""
    user = _env(ENV_USER)
    return {
        "configured": credentials_present(),
        "username_set": bool(user),
        "password_set": bool(_env(ENV_PASS)),
        "region": _env(ENV_REGION) or "US",
        "source": "environment" if os.environ.get(ENV_USER) else (".env" if user else "none"),
    }


def _resolve_credentials() -> tuple[str, str, str]:
    user = _env(ENV_USER)
    password = _env(ENV_PASS)
    region = (_env(ENV_REGION) or "US").upper()
    if not user or not password:
        raise SmartHomeError(
            f"SmartHQ credentials are not configured. Add {ENV_USER} and {ENV_PASS} to .env"
        )
    _remember_secret(password)
    _remember_secret(user)
    return user, password, region


@dataclass
class AcUnit:
    """One air conditioner, described without any credential material."""

    name: str
    mac: str
    appliance_type: str
    online: bool = False
    power_on: Optional[bool] = None
    target_f: Optional[float] = None
    ambient_f: Optional[float] = None
    mode: Optional[str] = None
    fan: Optional[str] = None
    filter_status: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def describe(self) -> str:
        bits = [self.name]
        if self.power_on is False:
            bits.append("off")
        elif self.power_on is True:
            parts = ["on"]
            if self.ambient_f is not None:
                parts.append(f"room {self.ambient_f:.0f}")
            if self.target_f is not None:
                parts.append(f"set {self.target_f:.0f}")
            if self.mode:
                parts.append(str(self.mode).lower())
            bits.append(", ".join(parts))
        else:
            bits.append("state unknown")
        return " - ".join(bits)


def _erd(appliance, code_name: str):
    """Read one ERD value by code name, tolerating models that lack it."""
    try:
        from gehomesdk import ErdCode

        code = getattr(ErdCode, code_name, None)
        if code is None:
            return None
        return appliance.get_erd_value(code)
    except Exception:
        return None


def _as_bool(value) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    name = getattr(value, "name", None) or str(value)
    upper = name.upper()
    if upper in {"ON", "TRUE", "1", "ENABLED"}:
        return True
    if upper in {"OFF", "FALSE", "0", "DISABLED"}:
        return False
    return None


def _as_name(value) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _as_number(value) -> Optional[float]:
    if value is None:
        return None
    for attr in ("fahrenheit", "temperature", "value"):
        inner = getattr(value, attr, None)
        if isinstance(inner, (int, float)):
            return float(inner)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _snapshot(appliance) -> AcUnit:
    type_name = _as_name(appliance.appliance_type) or "UNKNOWN"
    nickname = _erd(appliance, "APPLIANCE_NAME") or _erd(appliance, "USER_GIVEN_NAME")
    mac = str(getattr(appliance, "mac_addr", "") or "")
    return AcUnit(
        name=str(nickname or mac or "unnamed"),
        mac=mac,
        appliance_type=type_name,
        online=bool(getattr(appliance, "available", False)),
        power_on=_as_bool(_erd(appliance, "AC_POWER_STATUS")),
        target_f=_as_number(_erd(appliance, "AC_TARGET_TEMPERATURE")),
        ambient_f=_as_number(_erd(appliance, "AC_AMBIENT_TEMPERATURE")),
        mode=_as_name(_erd(appliance, "AC_OPERATION_MODE")),
        fan=_as_name(_erd(appliance, "AC_FAN_SETTING")),
        filter_status=_as_name(_erd(appliance, "AC_FILTER_STATUS")),
    )


async def _with_client(job: Callable[[Any], Any], *, timeout: float = CONNECT_TIMEOUT):
    """Connect, wait for appliances to report in, run one job, disconnect.

    The SDK's run loop never returns on its own, so it is driven as a task and
    cancelled once the job is done. Any failure is re-raised redacted.
    """
    try:
        from gehomesdk import GeWebsocketClient
        from gehomesdk.clients.const import (
            EVENT_APPLIANCE_INITIAL_UPDATE,
            EVENT_GOT_APPLIANCE_LIST,
        )
    except Exception as exc:
        raise SmartHomeError(f"gehomesdk is not installed correctly: {redact(exc)}") from None

    username, password, region = _resolve_credentials()
    client = GeWebsocketClient(username, password, region=region)

    listed = asyncio.Event()
    seen_any = asyncio.Event()

    async def on_list(_payload=None):
        listed.set()

    async def on_appliance(_payload=None):
        seen_any.set()

    client.add_event_handler(EVENT_GOT_APPLIANCE_LIST, on_list)
    client.add_event_handler(EVENT_APPLIANCE_INITIAL_UPDATE, on_appliance)

    runner = asyncio.create_task(client.async_get_credentials_and_run())
    try:
        done, _ = await asyncio.wait(
            [asyncio.create_task(listed.wait()), runner],
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if runner in done:
            exc = runner.exception()
            raise SmartHomeError(
                f"SmartHQ login or connection failed: {redact(exc) if exc else 'connection closed'}"
            ) from None
        if not listed.is_set():
            raise SmartHomeError("SmartHQ did not return an appliance list in time")

        # Appliance types and ERD values stream in after the list. Give them a
        # moment rather than reporting a fleet of 'state unknown'.
        try:
            await asyncio.wait_for(seen_any.wait(), timeout=SETTLE_SECONDS)
        except asyncio.TimeoutError:
            logger.debug("[SmartHome] no initial appliance update within settle window")
        await asyncio.sleep(1.5)

        return await job(client)
    finally:
        try:
            client.disconnect()
        except Exception:
            logger.debug("[SmartHome] disconnect failed", exc_info=True)
        runner.cancel()
        try:
            await runner
        except (asyncio.CancelledError, Exception):
            pass


def _ac_appliances(client) -> list:
    out = []
    for appliance in (client.appliances or {}).values():
        type_name = _as_name(appliance.appliance_type) or ""
        if type_name in AC_TYPE_NAMES:
            out.append(appliance)
    return out


async def async_discover(include_all: bool = False) -> list[AcUnit]:
    """List the GE appliances on the account (air conditioners by default)."""

    async def job(client):
        appliances = (
            list((client.appliances or {}).values()) if include_all else _ac_appliances(client)
        )
        return [_snapshot(a) for a in appliances]

    return await _with_client(job)


def _match(units_or_appliances, wanted: str, namer: Callable[[Any], str]):
    """Find one device by nickname, MAC, or a distinctive word from its name."""
    want = (wanted or "").strip().lower()
    if not want:
        return None
    candidates = list(units_or_appliances)
    for item in candidates:
        if namer(item).lower() == want:
            return item
    for item in candidates:
        if want in namer(item).lower():
            return item
    tight = re.sub(r"[^a-z0-9]", "", want)
    for item in candidates:
        if tight and tight in re.sub(r"[^a-z0-9]", "", namer(item).lower()):
            return item
    return None


async def async_ac_state(name: str) -> AcUnit:
    """Current state of one air conditioner."""

    async def job(client):
        appliance = _match(_ac_appliances(client), name, lambda a: _snapshot(a).name)
        if appliance is None:
            known = ", ".join(_snapshot(a).name for a in _ac_appliances(client)) or "none"
            raise SmartHomeError(f"No air conditioner matching {name!r}. Known units: {known}")
        return _snapshot(appliance)

    return await _with_client(job)


async def async_ac_set(
    name: str,
    *,
    power: Optional[bool] = None,
    temperature_f: Optional[int] = None,
    mode: Optional[str] = None,
    fan: Optional[str] = None,
) -> AcUnit:
    """Change one air conditioner and return its state afterwards."""
    if temperature_f is not None and not (60 <= int(temperature_f) <= 86):
        raise SmartHomeError("Target temperature must be between 60 and 86 degrees")

    async def job(client):
        from gehomesdk import ErdCode, ErdOnOff

        appliance = _match(_ac_appliances(client), name, lambda a: _snapshot(a).name)
        if appliance is None:
            known = ", ".join(_snapshot(a).name for a in _ac_appliances(client)) or "none"
            raise SmartHomeError(f"No air conditioner matching {name!r}. Known units: {known}")

        # Power first: setting a temperature on a unit that is off is a no-op on
        # most models, and turning it on afterwards would discard the setting.
        if power is not None:
            await appliance.async_set_erd_value(
                ErdCode.AC_POWER_STATUS, ErdOnOff.ON if power else ErdOnOff.OFF
            )
            await asyncio.sleep(1.5)
        if mode is not None:
            available = _erd(appliance, "AC_AVAILABLE_MODES")
            target = _coerce_enum("ErdAcOperationMode", mode, available)
            await appliance.async_set_erd_value(ErdCode.AC_OPERATION_MODE, target)
            await asyncio.sleep(0.8)
        if fan is not None:
            available = _erd(appliance, "AC_AVAILABLE_FAN_SPEEDS")
            target = _coerce_enum("ErdAcFanSetting", fan, available)
            await appliance.async_set_erd_value(ErdCode.AC_FAN_SETTING, target)
            await asyncio.sleep(0.8)
        if temperature_f is not None:
            await appliance.async_set_erd_value(
                ErdCode.AC_TARGET_TEMPERATURE, int(temperature_f)
            )
            await asyncio.sleep(0.8)

        try:
            await appliance.async_request_update()
            await asyncio.sleep(1.5)
        except Exception:
            logger.debug("[SmartHome] post-set refresh failed", exc_info=True)
        return _snapshot(appliance)

    return await _with_client(job)


def _coerce_enum(enum_name: str, wanted: str, available=None):
    """Turn a spoken word like 'cool' into the SDK enum member for it."""
    import gehomesdk

    enum = getattr(gehomesdk, enum_name, None)
    if enum is None:
        raise SmartHomeError(f"This build of gehomesdk has no {enum_name}")
    want = re.sub(r"[^a-z0-9]", "", (wanted or "").lower())
    for member in enum:
        if re.sub(r"[^a-z0-9]", "", member.name.lower()) == want:
            return member
    for member in enum:
        if want and want in re.sub(r"[^a-z0-9]", "", member.name.lower()):
            return member
    options = ", ".join(m.name.lower() for m in enum)
    raise SmartHomeError(f"{wanted!r} is not a valid setting. Options: {options}")


def _run(coro):
    """Run an async call from sync code, even with a loop already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def discover(include_all: bool = False) -> list[AcUnit]:
    return _run(async_discover(include_all=include_all))


def ac_state(name: str) -> AcUnit:
    return _run(async_ac_state(name))


def ac_set(name: str, **kwargs) -> AcUnit:
    return _run(async_ac_set(name, **kwargs))
