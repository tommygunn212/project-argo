from types import SimpleNamespace

import pytest

from core.llm_router import LLMRouter, load_llm_router_config


def test_legacy_llm_config_becomes_single_provider():
    cfg = load_llm_router_config({
        "llm": {
            "backend": "openai",
            "model": "gpt-4o-mini",
            "timeout_seconds": 12,
        }
    })

    assert cfg.mode == "single"
    assert cfg.primary == "openai_gpt_4o_mini"
    assert cfg.timeout_seconds == 12
    assert cfg.providers[cfg.primary].provider == "openai"
    assert cfg.providers[cfg.primary].model == "gpt-4o-mini"


def test_provider_chain_orders_primary_then_enabled_fallbacks():
    router = LLMRouter({
        "llm": {
            "mode": "fallback",
            "primary": "openai_fast",
            "fallbacks": ["ollama_qwen", "gemini_flash", "ollama_qwen"],
            "providers": {
                "openai_fast": {"provider": "openai", "model": "gpt-4o-mini", "enabled": True},
                "ollama_qwen": {"provider": "ollama", "model": "qwen:latest", "enabled": True},
                "gemini_flash": {"provider": "gemini", "model": "gemini-1.5-flash", "enabled": False},
            },
        }
    })

    assert [spec.provider_id for spec in router.provider_chain()] == ["openai_fast", "ollama_qwen"]


class FakeOpenAIStream:
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    def __iter__(self):
        for part in self.parts:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=part))]
            )

    def close(self):
        self.closed = True


class FakeOpenAIClient:
    def __init__(self, parts=None, exc=None):
        self.parts = parts or []
        self.exc = exc
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return FakeOpenAIStream(self.parts)


class FakeOllamaClient:
    def __init__(self, parts=None, exc=None):
        self.parts = parts or []
        self.exc = exc
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        for part in self.parts:
            yield {"response": part}


class FakeVoiceClients:
    def __init__(self, clients):
        self.clients = clients
        self.requests = []

    def get(self, backend, base_url=None):
        self.requests.append((backend, base_url))
        return self.clients[backend]


def test_openai_stream_yields_text_parts():
    openai = FakeOpenAIClient(["Hello", " there"])
    router = LLMRouter(
        {"llm": {"backend": "openai", "model": "gpt-4o-mini"}},
        FakeVoiceClients({"openai": openai}),
    )

    text = "".join(router.stream_text(
        prompt="Say hi",
        system_message="System",
        convo_messages=[{"role": "assistant", "content": "Earlier"}],
    ))

    assert text == "Hello there"
    assert openai.calls[0]["model"] == "gpt-4o-mini"
    assert openai.calls[0]["stream"] is True
    assert openai.calls[0]["messages"][0] == {"role": "system", "content": "System"}


def test_gpt55_uses_modern_chat_completion_parameters():
    openai = FakeOpenAIClient(["Useful answer"])
    router = LLMRouter(
        {"llm": {"backend": "openai", "model": "gpt-5.5"}},
        FakeVoiceClients({"openai": openai}),
    )

    assert "".join(router.stream_text(prompt="Hi", system_message="System")) == "Useful answer"
    request = openai.calls[0]
    assert request["model"] == "gpt-5.5"
    assert request["max_completion_tokens"] == 500
    assert "max_tokens" not in request
    assert "temperature" not in request


def test_fallback_moves_to_ollama_when_openai_fails_before_tokens():
    openai = FakeOpenAIClient(exc=RuntimeError("cloud down"))
    ollama = FakeOllamaClient(["local", " answer"])
    voice_clients = FakeVoiceClients({"openai": openai, "ollama": ollama})
    router = LLMRouter({
        "llm": {
            "mode": "fallback",
            "primary": "openai_fast",
            "fallbacks": ["ollama_qwen"],
            "providers": {
                "openai_fast": {"provider": "openai", "model": "gpt-4o-mini", "enabled": True},
                "ollama_qwen": {
                    "provider": "ollama",
                    "model": "qwen:latest",
                    "enabled": True,
                    "base_url": "http://ollama.test:11434",
                },
            },
        }
    }, voice_clients)

    text = "".join(router.stream_text(prompt="Hi", system_message="Sys"))

    assert text == "local answer"
    assert voice_clients.requests == [
        ("openai", None),
        ("ollama", "http://ollama.test:11434"),
    ]
    assert ollama.calls[0]["model"] == "qwen:latest"
    assert ollama.calls[0]["stream"] is True


def test_provider_error_after_tokens_does_not_fallback():
    class BrokenAfterToken:
        def __iter__(self):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"))]
            )
            raise RuntimeError("mid-stream failure")

        def close(self):
            pass

    openai = FakeOpenAIClient()
    openai._create = lambda **kwargs: BrokenAfterToken()
    openai.chat = SimpleNamespace(completions=SimpleNamespace(create=openai._create))
    ollama = FakeOllamaClient(["duplicate"])
    router = LLMRouter({
        "llm": {
            "mode": "fallback",
            "primary": "openai_fast",
            "fallbacks": ["ollama_qwen"],
            "providers": {
                "openai_fast": {"provider": "openai", "model": "gpt-4o-mini", "enabled": True},
                "ollama_qwen": {"provider": "ollama", "model": "qwen:latest", "enabled": True},
            },
        }
    }, FakeVoiceClients({"openai": openai, "ollama": ollama}))

    with pytest.raises(RuntimeError, match="mid-stream failure"):
        list(router.stream_text(prompt="Hi", system_message="Sys"))

    assert ollama.calls == []


def test_gemini_rest_provider_extracts_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Gemini "}, {"text": "answer"}]}}
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("core.llm_router.requests.post", fake_post)
    router = LLMRouter({
        "llm": {
            "primary": "gemini_flash",
            "providers": {
                "gemini_flash": {
                    "provider": "gemini",
                    "model": "gemini-1.5-flash",
                    "enabled": True,
                }
            },
            "timeout_seconds": 9,
        }
    })

    text = "".join(router.stream_text(
        prompt="Hi",
        system_message="System",
        convo_messages=[{"role": "assistant", "content": "Previous"}],
    ))

    assert text == "Gemini answer"
    assert calls[0][0].endswith("/models/gemini-1.5-flash:generateContent")
    assert calls[0][1]["params"] == {"key": "test-key"}
    assert calls[0][1]["timeout"] == 9
    assert calls[0][1]["json"]["contents"][0]["role"] == "model"
