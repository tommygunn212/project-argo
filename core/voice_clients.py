"""Reusable voice LLM clients with explicit, configurable idle timeouts."""
import threading


class VoiceClients:
    def __init__(self, config=None):
        self.config = config
        self._clients = {}
        self._lock = threading.Lock()

    def get(self, backend, base_url=None):
        settings = self.config.get("llm", {}) if self.config is not None else {}
        try:
            timeout = max(1.0, float(settings.get("timeout_seconds", 30)))
        except (TypeError, ValueError):
            timeout = 30.0
        host = base_url or settings.get("base_url", "http://127.0.0.1:11434")
        key = (backend, timeout, host if backend == "ollama" else "")
        with self._lock:
            if key not in self._clients:
                if backend == "openai":
                    from openai import OpenAI
                    self._clients[key] = OpenAI(timeout=timeout, max_retries=0)
                elif backend == "ollama":
                    from ollama import Client
                    self._clients[key] = Client(host=host, timeout=timeout)
                else:
                    raise ValueError("Unknown voice backend")
            return self._clients[key]

    def close(self):
        with self._lock:
            for client in self._clients.values():
                close = getattr(client, "close", None)
                if close:
                    close()
            self._clients.clear()
