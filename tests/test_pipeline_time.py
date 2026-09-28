from datetime import datetime, timezone
from types import SimpleNamespace

from core.pipeline_time import LOCATION_TO_TIMEZONE, PipelineTimeService


class Host:
    def __init__(self):
        self.logger = SimpleNamespace(error=lambda *_: None)
        self.deliveries = []

    def _deliver_canonical_response(self, *args, **kwargs):
        self.deliveries.append((args, kwargs))
        return True


def fixed_now(tz=None):
    current = datetime(2026, 9, 28, 12, 34, tzinfo=timezone.utc)
    return current.astimezone(tz) if tz else current


def test_time_status_uses_injected_clock():
    service = PipelineTimeService(Host(), now=fixed_now)

    assert service.format_time_status(None) == "It's 12:34 PM."
    assert service.format_time_status("day") == "Today is Monday."
    assert service.format_time_status("date") == "Today's date is Monday, September 28, 2026."


def test_world_time_uses_known_location_and_injected_clock():
    service = PipelineTimeService(Host(), now=fixed_now)

    assert LOCATION_TO_TIMEZONE["tokyo"] == "Asia/Tokyo"
    assert service.format_world_time("Tokyo") == "It's 9:34 PM in Tokyo."


def test_unknown_world_time_location_is_deterministic():
    service = PipelineTimeService(Host(), now=fixed_now)

    assert service.format_world_time("Qwerty") == (
        "I don't have timezone data for Qwerty. Try a major city name."
    )


def test_time_response_preserves_barge_in_suppression():
    host = Host()
    service = PipelineTimeService(host, now=fixed_now)

    assert service.respond_time_status(
        SimpleNamespace(subintent="day"), "id", False, None
    )
    assert host.deliveries[0][1]["suppress_barge_in_seconds"] == 2.0
