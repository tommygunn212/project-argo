"""Local and world-time formatting for the classic pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo


LOCATION_TO_TIMEZONE = {
    "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "rome": "Europe/Rome", "madrid": "Europe/Madrid", "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels", "vienna": "Europe/Vienna", "zurich": "Europe/Zurich",
    "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo", "copenhagen": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki", "dublin": "Europe/Dublin", "lisbon": "Europe/Lisbon",
    "athens": "Europe/Athens", "moscow": "Europe/Moscow", "istanbul": "Europe/Istanbul",
    "dubai": "Asia/Dubai", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "kolkata": "Asia/Kolkata", "chennai": "Asia/Kolkata",
    "singapore": "Asia/Singapore", "hong kong": "Asia/Hong_Kong", "hongkong": "Asia/Hong_Kong",
    "shanghai": "Asia/Shanghai", "beijing": "Asia/Shanghai", "tokyo": "Asia/Tokyo",
    "osaka": "Asia/Tokyo", "seoul": "Asia/Seoul", "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta", "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane", "perth": "Australia/Perth", "auckland": "Pacific/Auckland",
    "new york": "America/New_York", "nyc": "America/New_York",
    "new york city": "America/New_York", "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "chicago": "America/Chicago", "denver": "America/Denver",
    "phoenix": "America/Phoenix", "miami": "America/New_York", "boston": "America/New_York",
    "washington": "America/New_York", "dc": "America/New_York", "atlanta": "America/New_York",
    "dallas": "America/Chicago", "houston": "America/Chicago", "toronto": "America/Toronto",
    "vancouver": "America/Vancouver", "montreal": "America/Toronto",
    "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "cairo": "Africa/Cairo", "johannesburg": "Africa/Johannesburg", "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi", "uk": "Europe/London", "united kingdom": "Europe/London",
    "england": "Europe/London", "france": "Europe/Paris", "germany": "Europe/Berlin",
    "italy": "Europe/Rome", "spain": "Europe/Madrid", "japan": "Asia/Tokyo",
    "china": "Asia/Shanghai", "india": "Asia/Kolkata", "australia": "Australia/Sydney",
    "canada": "America/Toronto", "brazil": "America/Sao_Paulo", "russia": "Europe/Moscow",
    "south korea": "Asia/Seoul", "korea": "Asia/Seoul", "mexico": "America/Mexico_City",
    "egypt": "Africa/Cairo", "south africa": "Africa/Johannesburg",
    "california": "America/Los_Angeles", "texas": "America/Chicago",
    "florida": "America/New_York", "new jersey": "America/New_York",
    "hawaii": "Pacific/Honolulu", "alaska": "America/Anchorage",
}


class TimeHost(Protocol):
    logger: Any

    def _deliver_canonical_response(self, *args, **kwargs) -> bool: ...


class PipelineTimeService:
    def __init__(
        self,
        host: TimeHost,
        now: Callable[..., datetime] = datetime.now,
    ) -> None:
        self._host = host
        self._now = now

    def format_world_time(self, location: str) -> str:
        normalized = location.lower().strip()
        timezone_name = LOCATION_TO_TIMEZONE.get(normalized)
        if not timezone_name:
            timezone_name = next(
                (
                    timezone
                    for known_location, timezone in LOCATION_TO_TIMEZONE.items()
                    if known_location in normalized or normalized in known_location
                ),
                None,
            )
        if not timezone_name:
            return f"I don't have timezone data for {location}. Try a major city name."
        try:
            current = self._now(ZoneInfo(timezone_name))
            time_text = current.strftime("%I:%M %p").lstrip("0")
            return f"It's {time_text} in {location.title()}."
        except Exception as exc:
            self._host.logger.error(f"[WORLD_TIME] Error getting time for {location}: {exc}")
            return f"Couldn't get the time for {location}."

    def respond_world_time(
        self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        location = getattr(intent, "target", None) if intent else None
        message = (
            self.format_world_time(location)
            if location
            else "I didn't catch the location. Where would you like to know the time?"
        )
        return self._deliver(message, interaction_id, replay_mode, overrides)

    def format_time_status(self, subintent: str | None) -> str:
        current = self._now()
        if subintent == "day":
            return f"Today is {current.strftime('%A')}."
        if subintent == "date":
            return f"Today's date is {current.strftime('%A, %B %d, %Y')}."
        return f"It's {current.strftime('%I:%M %p').lstrip('0')}."

    def respond_time_status(
        self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        subintent = getattr(intent, "subintent", None) if intent else None
        return self._deliver(
            self.format_time_status(subintent), interaction_id, replay_mode, overrides
        )

    def _deliver(self, message, interaction_id, replay_mode, overrides) -> bool:
        return self._host._deliver_canonical_response(
            message,
            interaction_id,
            replay_mode,
            overrides,
            enforce_confidence=False,
            force_tts=True,
            suppress_barge_in_seconds=2.0,
        )
