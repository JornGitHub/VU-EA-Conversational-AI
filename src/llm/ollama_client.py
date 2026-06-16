"""Dependency-free Ollama client for local grounded answer generation."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request


def generate_with_ollama(
    prompt: str,
    model: str = "qwen3:30b-instruct",
    base_url: str = "http://localhost:11434",
    timeout: int = 120,
) -> str:
    """Generate a response with Ollama's /api/chat endpoint."""
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(
            f"Ollama gaf een HTTP-fout terug ({exc.code}) voor model '{model}': {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            f"Kan geen verbinding maken met Ollama. Controleer of Ollama draait op {base_url}."
        ) from exc

    try:
        result = json.loads(raw_body)
        content = result["message"]["content"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Ollama gaf een onverwacht antwoord terug; verwachtte JSON met message.content."
        ) from exc

    if not isinstance(content, str):
        raise RuntimeError("Ollama gaf een onverwacht antwoord terug: message.content is geen tekst.")
    return content
