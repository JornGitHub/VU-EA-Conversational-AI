"""Ollama client for local grounded answer generation.

Three settings decide how long a local model makes the user wait:

* **thinking mode** - Qwen3 and other reasoning models emit a long hidden
  reasoning block first. Ollama returns it in ``message.thinking``, not in
  ``message.content``, so the UI shows nothing at all while it runs. This client
  asks for ``think: false`` and retries once without the field for servers or
  models that reject it.
* **prompt size** - handled in ``prompt_builder``: the prompt carries the facts
  once instead of the whole retrieval payload.
* **generation options** - a bounded answer length and a temperature suited to
  formulating, plus ``keep_alive`` so the model stays loaded between questions
  instead of being re-read from disk every time.
"""

from __future__ import annotations

import json
from typing import Any, Iterator


DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 300
# Keep the model in memory between questions; loading an 8B model costs seconds
# to minutes and would otherwise repeat for every single question.
DEFAULT_KEEP_ALIVE = "30m"
DEFAULT_OPTIONS: dict[str, Any] = {
    "temperature": 0.3,
    "top_p": 0.9,
    # The prompt is compact by design, so a small context window is enough and
    # keeps both memory use and prompt processing low.
    "num_ctx": 4096,
    # Bound the answer: formulating a grounded answer needs a few hundred tokens.
    "num_predict": 400,
}

_SESSION: "requests.Session | None" = None


def _requests():
    """Import requests on first use.

    It costs about 290 ms to import, and a question answered from local
    documentation never touches it. Annotations are strings here
    (``from __future__ import annotations``), so nothing else needs it either.
    """
    import requests

    return requests


def _session() -> "requests.Session":
    """Return a session that ignores proxy environment variables.

    Ollama runs on localhost; routing those calls through a corporate proxy set
    in HTTP(S)_PROXY makes the LLM layer fail for no reason.
    """
    global _SESSION
    if _SESSION is None:
        session = _requests().Session()
        session.trust_env = False
        _SESSION = session
    return _SESSION


def build_payload(
    prompt: str,
    model: str,
    *,
    stream: bool,
    think: bool | None = False,
    options: dict[str, Any] | None = None,
    keep_alive: str = DEFAULT_KEEP_ALIVE,
) -> dict[str, Any]:
    """Return the /api/chat request body used for both call styles."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
        "keep_alive": keep_alive,
        "options": {**DEFAULT_OPTIONS, **(options or {})},
    }
    if think is not None:
        payload["think"] = think
    return payload


def _connection_error(exc: Exception, base_url: str) -> RuntimeError:
    return RuntimeError(
        f"Kan geen verbinding maken met Ollama. Controleer of Ollama draait op {base_url}. "
        f"Details: {type(exc).__name__}: {exc}"
    )


def _http_error(exc: "requests.exceptions.HTTPError", model: str) -> RuntimeError:
    detail = exc.response.text if exc.response is not None else str(exc)
    if "not found" in detail.lower():
        return RuntimeError(
            f"Ollama kent het model '{model}' niet. Haal het op met: ollama pull {model}. Details: {detail}"
        )
    return RuntimeError(f"Ollama gaf een HTTP-fout terug voor model '{model}': {detail}")


def _rejects_think(response: "requests.Response") -> bool:
    """True when the server refused the request because of the ``think`` field."""
    if response.status_code != 400:
        return False
    return "think" in (response.text or "").lower()


def generate_with_ollama(
    prompt: str,
    model: str = "qwen3:8b",
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    options: dict[str, Any] | None = None,
) -> str:
    """Generate a response with Ollama's /api/chat endpoint."""
    url = base_url.rstrip("/") + "/api/chat"

    for think in (False, None):
        payload = build_payload(prompt, model, stream=False, think=think, options=options)
        try:
            response = _session().post(url, json=payload, timeout=timeout)
            if think is not None and _rejects_think(response):
                continue  # older server or non-thinking model: retry without the field
            response.raise_for_status()
        except _requests().exceptions.HTTPError as exc:
            raise _http_error(exc, model) from exc
        except (_requests().exceptions.ConnectionError, _requests().exceptions.Timeout) as exc:
            raise _connection_error(exc, base_url) from exc

        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "Ollama gaf een onverwacht antwoord terug; verwachtte JSON met message.content."
            ) from exc

        if not isinstance(content, str):
            raise RuntimeError("Ollama gaf een onverwacht antwoord terug: message.content is geen tekst.")
        return content

    raise RuntimeError(f"Ollama accepteerde het verzoek voor model '{model}' niet.")


def stream_with_ollama(
    prompt: str,
    model: str = "qwen3:8b",
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    options: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Yield answer fragments from Ollama's /api/chat streaming response.

    Fragments are yielded as the model writes them, so a local model on CPU shows
    progress instead of a blank screen.
    """
    url = base_url.rstrip("/") + "/api/chat"

    for think in (False, None):
        payload = build_payload(prompt, model, stream=True, think=think, options=options)
        try:
            with _session().post(url, json=payload, timeout=timeout, stream=True) as response:
                if think is not None and _rejects_think(response):
                    continue  # older server or non-thinking model: retry without the field
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    fragment = (event.get("message") or {}).get("content")
                    if fragment:
                        yield fragment
                    if event.get("done"):
                        return
                return
        except _requests().exceptions.HTTPError as exc:
            raise _http_error(exc, model) from exc
        except (_requests().exceptions.ConnectionError, _requests().exceptions.Timeout) as exc:
            raise _connection_error(exc, base_url) from exc


def warm_up(model: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 600) -> bool:
    """Load the model into memory without generating a real answer.

    Returns True when the model is loaded and ready. Loading an 8B model reads
    several GB from disk, so doing it once up front keeps the first real question
    from looking like the app hangs.
    """
    url = base_url.rstrip("/") + "/api/chat"
    payload = build_payload("hoi", model, stream=False, think=False, options={"num_predict": 1})
    try:
        response = _session().post(url, json=payload, timeout=timeout)
        if _rejects_think(response):
            payload = build_payload("hoi", model, stream=False, think=None, options={"num_predict": 1})
            response = _session().post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except _requests().exceptions.RequestException:
        return False
    return True
