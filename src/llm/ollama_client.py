"""Ollama client for local grounded answer generation."""

from __future__ import annotations

import requests

_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    """Return a session that ignores proxy environment variables.

    Ollama runs on localhost; routing those calls through a corporate proxy set
    in HTTP(S)_PROXY makes the LLM layer fail for no reason.
    """
    global _SESSION
    if _SESSION is None:
        session = requests.Session()
        session.trust_env = False
        _SESSION = session
    return _SESSION


def generate_with_ollama(
    prompt: str,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434",
    timeout: int = 300,
) -> str:
    """Generate a response with Ollama's /api/chat endpoint."""
    url = base_url.rstrip("/") + "/api/chat"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        response = _session().post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        raise RuntimeError(
            f"Ollama gaf een HTTP-fout terug voor model '{model}': {detail}"
        ) from exc
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise RuntimeError(
            f"Kan geen verbinding maken met Ollama. Controleer of Ollama draait op {base_url}. "
            f"Details: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        result = response.json()
        content = result["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Ollama gaf een onverwacht antwoord terug; verwachtte JSON met message.content."
        ) from exc

    if not isinstance(content, str):
        raise RuntimeError("Ollama gaf een onverwacht antwoord terug: message.content is geen tekst.")

    return content