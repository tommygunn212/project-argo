"""Provider router for ARGO LLM calls.

The router keeps model/provider selection deterministic and centralized. It
supports the existing legacy config shape while adding named providers and a
fallback chain for Ollama, OpenAI, and Gemini.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import requests

from core.instrumentation import log_event


@dataclass(frozen=True)
class LLMProviderSpec:
    provider_id: str
    provider: str
    model: str
    enabled: bool = True
    base_url: str = ""


@dataclass(frozen=True)
class LLMRouterConfig:
    mode: str
    primary: str
    fallbacks: tuple[str, ...]
    providers: dict[str, LLMProviderSpec]
    timeout_seconds: float


def _config_get(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        value: Any = config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def load_llm_router_config(config: Any = None) -> LLMRouterConfig:
    llm = _config_get(config, "llm", {}) or {}
    if not isinstance(llm, dict):
        llm = {}

    timeout = llm.get("timeout_seconds", 30)
    try:
        timeout_seconds = max(1.0, float(timeout))
    except (TypeError, ValueError):
        timeout_seconds = 30.0

    provider_defs = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    providers: dict[str, LLMProviderSpec] = {}
    for provider_id, raw in provider_defs.items():
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip().lower()
        model = str(raw.get("model") or "").strip()
        if not provider or not model:
            continue
        providers[str(provider_id)] = LLMProviderSpec(
            provider_id=str(provider_id),
            provider=provider,
            model=model,
            enabled=_as_bool(raw.get("enabled", True), True),
            base_url=str(raw.get("base_url") or "").strip(),
        )

    legacy_backend = str(llm.get("backend", "ollama") or "ollama").strip().lower()
    legacy_model = str(llm.get("model", "qwen:latest") or "qwen:latest").strip()
    legacy_id = f"{legacy_backend}_{legacy_model}".replace(":", "_").replace("/", "_").replace("-", "_")
    if not providers:
        providers[legacy_id] = LLMProviderSpec(
            provider_id=legacy_id,
            provider=legacy_backend,
            model=legacy_model,
            enabled=True,
            base_url=str(llm.get("base_url") or "").strip(),
        )

    primary = str(llm.get("primary") or legacy_id)
    if primary not in providers:
        primary = next(iter(providers))

    raw_fallbacks = llm.get("fallbacks", ())
    if isinstance(raw_fallbacks, str):
        fallbacks = (raw_fallbacks,)
    else:
        fallbacks = tuple(str(item) for item in raw_fallbacks or ())

    mode = str(llm.get("mode") or ("fallback" if fallbacks else "single")).strip().lower()
    if mode not in {"single", "fallback"}:
        mode = "fallback" if fallbacks else "single"

    return LLMRouterConfig(
        mode=mode,
        primary=primary,
        fallbacks=fallbacks,
        providers=providers,
        timeout_seconds=timeout_seconds,
    )


class LLMRouter:
    def __init__(self, config: Any = None, voice_clients: Any = None):
        self.config = load_llm_router_config(config)
        self.voice_clients = voice_clients
        self.last_provider_id = ""
        self.last_provider = ""
        self.last_model = ""

    @property
    def primary_model_name(self) -> str:
        primary = self.config.providers.get(self.config.primary)
        return primary.model if primary else "unknown"

    def provider_chain(self) -> list[LLMProviderSpec]:
        ids = [self.config.primary]
        if self.config.mode == "fallback":
            ids.extend(self.config.fallbacks)
        seen: set[str] = set()
        chain: list[LLMProviderSpec] = []
        for provider_id in ids:
            if provider_id in seen:
                continue
            seen.add(provider_id)
            spec = self.config.providers.get(provider_id)
            if spec and spec.enabled:
                chain.append(spec)
        return chain

    def warmup(self) -> None:
        chain = self.provider_chain()
        if not chain:
            raise RuntimeError("No enabled LLM providers configured")
        spec = chain[0]
        if spec.provider == "ollama":
            client = self._client("ollama", spec)
            client.generate(model=spec.model, prompt="hi", stream=False)
        elif spec.provider == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY not set")
        elif spec.provider == "gemini":
            if not self._gemini_api_key():
                raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY not set")
        else:
            raise RuntimeError(f"Unknown LLM provider: {spec.provider}")

    def stream_text(
        self,
        *,
        prompt: str,
        system_message: str,
        convo_messages: Iterable[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        interaction_id: str = "",
        model_override: str | None = None,
    ) -> Iterator[str]:
        last_error: Exception | None = None
        chain = self.provider_chain()
        if not chain:
            raise RuntimeError("No enabled LLM providers configured")

        for spec in chain:
            model = model_override or spec.model
            yielded = False
            self.last_provider_id = spec.provider_id
            self.last_provider = spec.provider
            self.last_model = model
            log_event(
                f"LLM_PROVIDER_START id={spec.provider_id} provider={spec.provider} model={model}",
                stage="llm",
                interaction_id=interaction_id,
            )
            try:
                for part in self._stream_provider(
                    spec,
                    model=model,
                    prompt=prompt,
                    system_message=system_message,
                    convo_messages=list(convo_messages or ()),
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yielded = True
                    yield part
                log_event(
                    f"LLM_PROVIDER_DONE id={spec.provider_id} provider={spec.provider} model={model}",
                    stage="llm",
                    interaction_id=interaction_id,
                )
                return
            except Exception as exc:
                last_error = exc
                log_event(
                    f"LLM_PROVIDER_ERROR id={spec.provider_id} provider={spec.provider} error={type(exc).__name__}",
                    stage="llm",
                    interaction_id=interaction_id,
                )
                if yielded:
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("No LLM provider produced a response")

    def _stream_provider(
        self,
        spec: LLMProviderSpec,
        *,
        model: str,
        prompt: str,
        system_message: str,
        convo_messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        if spec.provider == "openai":
            yield from self._stream_openai(model, prompt, system_message, convo_messages, temperature, max_tokens)
        elif spec.provider == "ollama":
            yield from self._stream_ollama(spec, model, prompt, system_message, temperature, max_tokens)
        elif spec.provider == "gemini":
            yield from self._stream_gemini(spec, model, prompt, system_message, convo_messages, temperature, max_tokens)
        else:
            raise ValueError(f"Unknown LLM provider: {spec.provider}")

    def _stream_openai(
        self,
        model: str,
        prompt: str,
        system_message: str,
        convo_messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        client = self._client("openai")
        messages = [{"role": "system", "content": system_message}]
        messages.extend(convo_messages)
        messages.append({"role": "user", "content": prompt})
        request = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        # GPT-5.2 accepts temperature only with reasoning disabled, and GPT-5
        # uses max_completion_tokens rather than the legacy max_tokens parameter.
        # Older models keep their existing request shape.
        if model.lower().startswith("gpt-5"):
            request["max_completion_tokens"] = max_tokens
            if model.lower().startswith("gpt-5.2"):
                request["reasoning_effort"] = "none"
                request["temperature"] = temperature
        else:
            request["temperature"] = temperature
            request["max_tokens"] = max_tokens
        stream = client.chat.completions.create(**request)
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                part = delta.content if delta and delta.content else ""
                if part:
                    yield part
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

    def _stream_ollama(
        self,
        spec: LLMProviderSpec,
        model: str,
        prompt: str,
        system_message: str,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        client = self._client("ollama", spec)
        ollama_prompt = system_message + "\n\n" + prompt
        stream = client.generate(
            model=model,
            prompt=ollama_prompt,
            stream=True,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        )
        close = getattr(stream, "close", None)
        try:
            for chunk in stream:
                part = chunk.get("response", "") if isinstance(chunk, dict) else ""
                if part:
                    yield part
        finally:
            if close:
                close()

    def _stream_gemini(
        self,
        spec: LLMProviderSpec,
        model: str,
        prompt: str,
        system_message: str,
        convo_messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        api_key = self._gemini_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY not set")
        base_url = spec.base_url or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
        contents = self._gemini_contents(convo_messages, prompt)
        payload = {
            "systemInstruction": {"parts": [{"text": system_message}]},
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        response = requests.post(url, params={"key": api_key}, json=payload, timeout=self.config.timeout_seconds)
        response.raise_for_status()
        text = self._extract_gemini_text(response.json())
        if text:
            yield text

    def _client(self, backend: str, spec: LLMProviderSpec | None = None) -> Any:
        if self.voice_clients is None:
            raise RuntimeError("VoiceClients is required for OpenAI/Ollama providers")
        if backend == "ollama" and spec and spec.base_url:
            return self.voice_clients.get("ollama", base_url=spec.base_url)
        return self.voice_clients.get(backend)

    @staticmethod
    def _gemini_api_key() -> str:
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

    @staticmethod
    def _gemini_contents(convo_messages: list[dict[str, Any]], prompt: str) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in convo_messages[-8:]:
            role = str(message.get("role", "user")).lower()
            text = str(message.get("content", "") or "")
            if not text:
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        return contents

    @staticmethod
    def _extract_gemini_text(payload: dict[str, Any]) -> str:
        parts: list[str] = []
        for candidate in payload.get("candidates", []) or []:
            content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
            for part in content.get("parts", []) or []:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
        return "".join(parts)
