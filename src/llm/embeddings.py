"""Local embedding client for the free-only semantic search layer.

Embeddings are produced by the same local Ollama server that formulates answers,
so the project stays key-free and offline-capable: no hosted embedding API, no
vector database service. ``/api/embed`` is used when available and the legacy
``/api/embeddings`` endpoint is the fallback for older Ollama versions.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterable, Sequence

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 120


class EmbeddingError(RuntimeError):
    """Raised when the local embedding endpoint is unavailable or unusable."""


# Ollama always runs locally, so proxy environment variables must not apply.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _OPENER.open(request, timeout=timeout) as response:  # noqa: S310 - fixed localhost URL.
        return json.loads(response.read().decode("utf-8"))


def _vectors_from_payload(payload: dict) -> list[list[float]]:
    if isinstance(payload.get("embeddings"), list):
        return [[float(value) for value in vector] for vector in payload["embeddings"]]
    if isinstance(payload.get("embedding"), list):
        return [[float(value) for value in payload["embedding"]]]
    raise EmbeddingError("Ollama gaf geen embeddings terug in het antwoord.")


def embed_texts(
    texts: Sequence[str],
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[list[float]]:
    """Return one embedding vector per input text.

    Raises ``EmbeddingError`` when the server is unreachable or the model is not
    installed, so callers can fall back to lexical-only retrieval.
    """
    items = [str(text or "") for text in texts]
    if not items:
        return []

    root = base_url.rstrip("/")
    try:
        payload = _post_json(f"{root}/api/embed", {"model": model, "input": items}, timeout)
        vectors = _vectors_from_payload(payload)
        if len(vectors) == len(items):
            return vectors
    except urllib.error.HTTPError:
        vectors = []
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise EmbeddingError(
            f"Kan geen verbinding maken met Ollama op {base_url} voor embeddings. Details: {exc}"
        ) from exc
    except EmbeddingError:
        vectors = []

    # Legacy endpoint: one request per text.
    legacy: list[list[float]] = []
    for item in items:
        try:
            payload = _post_json(f"{root}/api/embeddings", {"model": model, "prompt": item}, timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise EmbeddingError(
                f"Ollama kon geen embedding maken met model '{model}'. Details: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise EmbeddingError(
                f"Kan geen verbinding maken met Ollama op {base_url} voor embeddings. Details: {exc}"
            ) from exc
        legacy.extend(_vectors_from_payload(payload))
    if len(legacy) != len(items):
        raise EmbeddingError("Ollama gaf een ander aantal embeddings terug dan gevraagd.")
    return legacy


def embed_text(
    text: str,
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[float]:
    """Return the embedding vector for one text."""
    vectors = embed_texts([text], model=model, base_url=base_url, timeout=timeout)
    if not vectors:
        raise EmbeddingError("Ollama gaf geen embedding terug.")
    return vectors[0]


def iter_batches(items: Sequence[str], batch_size: int) -> Iterable[Sequence[str]]:
    """Yield ``items`` in batches, used to keep embedding requests small."""
    size = max(1, batch_size)
    for start in range(0, len(items), size):
        yield items[start : start + size]
