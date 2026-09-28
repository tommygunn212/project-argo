"""Ollama transport and terminal streaming for the legacy wrapper."""

from __future__ import annotations

import json
import sys

import requests

from wrapper.conversation_history import validate_voice_compliance


def generate_ollama_response(full_prompt: bytes) -> str:
    """Validate the local ARGO model, stream its response, and return full text."""
    url = "http://localhost:11434/api/generate"
    try:
        response = requests.head("http://localhost:11434/api/tags", timeout=2)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("Error: Ollama server is not running.", file=sys.stderr)
        print("Start Ollama with: ollama serve", file=sys.stderr)
        raise SystemExit(1)
    except requests.exceptions.Timeout:
        print("Error: Ollama server is not responding.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Error connecting to Ollama: {exc}", file=sys.stderr)
        raise SystemExit(1)

    try:
        tags_response = requests.get("http://localhost:11434/api/tags", timeout=2)
        tags_response.raise_for_status()
        models = tags_response.json().get("models", [])
        model_names = [model.get("name") for model in models]
        if not any(name.startswith("argo") for name in model_names):
            print("Error: Model 'argo' not found.", file=sys.stderr)
            available = ", ".join(model_names) if model_names else "none"
            print(f"Available models: {available}", file=sys.stderr)
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error validating model: {exc}", file=sys.stderr)
        raise SystemExit(1)

    response = requests.post(
        url,
        json={
            "model": "argo",
            "prompt": full_prompt.decode("utf-8"),
            "stream": True,
        },
        stream=True,
    )
    response.raise_for_status()

    output_lines = []
    max_characters = 3000
    characters_printed = 0
    output_cutoff = False
    token_buffer = []
    buffer_size = 10

    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        token = data.get("response", "")
        output_lines.append(token)

        if output_cutoff:
            continue
        if characters_printed + len(token) > max_characters:
            if token_buffer:
                print("".join(token_buffer), end="", flush=True)
                token_buffer.clear()
            output_cutoff = True
            print(
                '\n— Output paused to keep things readable. Say "continue" to go deeper.',
                flush=True,
            )
            continue

        characters_printed += len(token)
        token_buffer.append(token)
        if len(token_buffer) >= buffer_size:
            print("".join(token_buffer), end="", flush=True)
            token_buffer.clear()

    if token_buffer:
        print("".join(token_buffer), flush=True)

    return validate_voice_compliance("".join(output_lines).strip())
