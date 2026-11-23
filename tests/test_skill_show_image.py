"""Offline checks for image generation and delivery to the dashboard."""

import asyncio
import base64
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from argo_skills import show_image as skill


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+aJ1sAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def services(monkeypatch):
    """Replace credentials, OpenAI, and dashboard access before every call."""
    key = Mock(return_value=True)
    generate = AsyncMock(return_value=SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(PNG).decode("ascii"))]
    ))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.images = SimpleNamespace(generate=generate)
    factory = Mock(return_value=client)
    display = AsyncMock(return_value="Showing 'Generated picture' on the dashboard.")
    monkeypatch.setattr(skill, "ensure_openai_key", key)
    monkeypatch.setattr(skill, "AsyncOpenAI", factory)
    monkeypatch.setattr(skill, "display_image", display)
    return SimpleNamespace(
        key=key, generate=generate, client=client, factory=factory, display=display,
    )


def test_generates_and_displays_png(services):
    events = Mock()
    events.attach_mock(services.key, "key")
    events.attach_mock(services.factory, "client")
    result = asyncio.run(skill.show_image("  A cat cooking soup  "))

    assert result == "I've put your picture on the dashboard."
    assert events.mock_calls[0][0] == "key"
    services.key.assert_called_once_with()
    services.factory.assert_called_once_with(timeout=50.0, max_retries=0)
    services.generate.assert_awaited_once_with(
        model="gpt-image-1", prompt="A cat cooking soup", n=1, output_format="png",
    )
    services.client.__aexit__.assert_awaited_once()
    services.display.assert_awaited_once_with(
        "Generated picture", png_bytes=PNG, mime="image/png",
        caption="A cat cooking soup",
    )
    assert skill.TOOLS == [skill.show_image]
    assert inspect.iscoroutinefunction(skill.show_image)
    assert skill.show_image.__annotations__ == {"prompt": str, "return": str}
    assert "Tommy" in inspect.getdoc(skill.show_image)


def test_blank_prompt_skips_services(services):
    assert "Tell me what picture" in asyncio.run(skill.show_image(" \n\t"))
    services.key.assert_not_called()
    services.factory.assert_not_called()
    services.display.assert_not_awaited()


def test_missing_key_skips_generation(services):
    services.key.return_value = False
    assert "API key" in asyncio.run(skill.show_image("A cat"))
    services.factory.assert_not_called()
    services.display.assert_not_awaited()


@pytest.mark.parametrize("data", [None, [], [SimpleNamespace(b64_json=None)],
                                  [SimpleNamespace(b64_json="")],
                                  [SimpleNamespace(b64_json="not base64!")]])
def test_invalid_image_is_not_displayed(services, data):
    services.generate.return_value = SimpleNamespace(data=data)
    assert asyncio.run(skill.show_image("A cat")) == (
        "I couldn't generate a picture. Please try again."
    )
    services.display.assert_not_awaited()


@pytest.mark.parametrize("failure", [RuntimeError("private-request-detail"),
                                      asyncio.TimeoutError()])
def test_generation_failure_is_safe(services, failure):
    services.generate.side_effect = failure
    assert asyncio.run(skill.show_image("A cat")) == (
        "I couldn't generate a picture. Please try again."
    )
    services.client.__aexit__.assert_awaited_once()
    services.display.assert_not_awaited()


def test_dashboard_failure_does_not_claim_success(services):
    services.display.side_effect = RuntimeError("private-dashboard-detail")
    assert asyncio.run(skill.show_image("A cat")) == (
        "I created the picture, but couldn't show it on the dashboard."
    )


def test_cancellation_propagates(services):
    services.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(skill.show_image("A cat"))
    services.client.__aexit__.assert_awaited_once()
    services.display.assert_not_awaited()
