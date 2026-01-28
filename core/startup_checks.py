"""Startup checks for external dependencies."""

import requests


def check_ollama() -> bool:
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=0.5)
        return response.status_code == 200
    except Exception:
        return False
