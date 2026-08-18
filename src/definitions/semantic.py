"""Local semantic (dense) search over the same official documentation.

Lexical ranking answers questions that use the wording of the documentation.
Questions that use different words ("hoeveel buitenlandse studenten tellen mee?")
can miss it entirely. This module adds a dense retrieval layer on top of exactly
the same local sources, so a miss can still surface the right fragment.

Design constraints kept from the rest of the project:

* free and key-free - vectors come from the local Ollama server;
* offline-capable - the index is a local file, no vector database service;
* never authoritative - semantic hits are labelled as such, and the lexical
  layer keeps priority for definitions;
* degrades gracefully - without Ollama or without a built index every function
  returns "unavailable" instead of raising.

Build the index with ``python main.py --build-embeddings``.
"""

from __future__ import annotations

import json
import math
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from src.definitions.corpus import (
    CHUNKS_PATH,
    CURATED_PATH,
    INDEX_PATH,
    load_chunks,
    load_curated_definitions,
    load_index_definitions,
)
from src.definitions.inschrijvingen_catalog import FIELD_CATALOG_PATH, load_catalog
from src.llm.embeddings import (
    DEFAULT_BASE_URL,
    DEFAULT_EMBED_MODEL,
    EmbeddingError,
    embed_texts,
    iter_batches,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SEMANTIC_DIR = DATA_DIR / "semantic_index"
VECTORS_PATH = SEMANTIC_DIR / "vectors.f32"
META_PATH = SEMANTIC_DIR / "meta.json"

SOURCE_FILES = (CURATED_PATH, INDEX_PATH, CHUNKS_PATH, FIELD_CATALOG_PATH)
PREVIEW_CHARS = 400
EMBED_CHARS = 1200
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.45

Progress = Callable[[str], None]


@dataclass
class SemanticIndex:
    """An in-memory view of the on-disk vector store."""

    model: str
    dim: int
    built_at: str
    items: list[dict[str, Any]]
    vectors: Any  # numpy array when numpy is installed, array("f") otherwise
    source_signature: dict[str, list[float]]
    uses_numpy: bool

    def __len__(self) -> int:
        return len(self.items)

    def is_stale(self) -> bool:
        """True when a knowledge file changed after the index was built."""
        return self.source_signature != _source_signature()

    def search(self, vector: Sequence[float], top_k: int = DEFAULT_TOP_K, min_score: float = DEFAULT_MIN_SCORE) -> list[dict[str, Any]]:
        """Return the closest items for an already-normalised query vector."""
        if not self.items or len(vector) != self.dim:
            return []

        if self.uses_numpy:
            import numpy as np

            scores = self.vectors @ np.asarray(vector, dtype="float32")
            order = np.argsort(-scores)[:top_k]
            ranked = [(int(i), float(scores[i])) for i in order]
        else:
            scores = []
            for row in range(len(self.items)):
                start = row * self.dim
                chunk = self.vectors[start : start + self.dim]
                scores.append((row, sum(a * b for a, b in zip(chunk, vector))))
            ranked = sorted(scores, key=lambda pair: pair[1], reverse=True)[:top_k]

        hits = []
        for row, score in ranked:
            if score < min_score:
                continue
            hit = dict(self.items[row])
            hit["score"] = round(float(score), 4)
            hit["source_tier"] = "official_documentation"
            hit["retrieval"] = "semantic"
            hits.append(hit)
        return hits


def _display_path(path: Path) -> str:
    """Return a repo-relative path when possible, else the absolute path."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _source_signature() -> dict[str, list[float]]:
    signature: dict[str, list[float]] = {}
    for path in SOURCE_FILES:
        try:
            stat = path.stat()
        except OSError:
            continue
        signature[path.name] = [stat.st_mtime, stat.st_size]
    return signature


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return list(vector)
    return [value / norm for value in vector]


def _item(kind: str, entry: dict[str, Any], text: str, term: str) -> dict[str, Any] | None:
    body = " ".join(str(text or "").split())
    if len(body) < 40:
        return None
    return {
        "kind": kind,
        "term": term,
        "text": body[:EMBED_CHARS],
        "preview": body[:PREVIEW_CHARS],
        "source_document": entry.get("source_document"),
        "source_path": entry.get("source_path"),
        "page": entry.get("page"),
        "chunk_id": entry.get("chunk_id"),
    }


def collect_items() -> list[dict[str, Any]]:
    """Collect every local documentation snippet worth embedding."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: dict[str, Any] | None) -> None:
        if candidate is None:
            return
        key = f"{candidate['kind']}::{candidate['text'][:160].lower()}"
        if key in seen:
            return
        seen.add(key)
        items.append(candidate)

    for field in load_catalog():
        text = f"{field.get('field_name', '')}. {field.get('description', '')}"
        notes = " ".join(str(note) for note in field.get("notes", []) or [])
        add(_item("field", field, f"{text} {notes}", str(field.get("field_name", ""))))

    for entry in load_curated_definitions():
        add(_item("definition", entry, f"{entry.get('term', '')}. {entry.get('definition', '')}", str(entry.get("term", ""))))

    for entry in load_index_definitions():
        add(_item("index", entry, f"{entry.get('term', '')}. {entry.get('definition', '')}", str(entry.get("term", ""))))

    for entry in load_chunks():
        add(_item("chunk", entry, str(entry.get("text", "")), str(entry.get("source_document", "Documentfragment"))))

    return items


def build_semantic_index(
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    batch_size: int = 16,
    progress: Progress | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Embed every local snippet and write the vector store.

    Returns a report dict; raises ``EmbeddingError`` when the local embedding
    endpoint is unavailable so callers can explain what to install.
    """
    log = progress or (lambda _message: None)
    items = collect_items()
    log(f"Semantische index bouwen voor {len(items)} fragmenten met model '{model}'...")
    if dry_run:
        return {"items": len(items), "model": model, "written": False, "dry_run": True}

    vectors: list[list[float]] = []
    dim = 0
    done = 0
    for batch in iter_batches([item["text"] for item in items], batch_size):
        for vector in embed_texts(list(batch), model=model, base_url=base_url):
            normalized = _normalize(vector)
            dim = dim or len(normalized)
            if len(normalized) != dim:
                raise EmbeddingError("Ollama gaf embeddings met wisselende lengte terug.")
            vectors.append(normalized)
        done += len(batch)
        if done % (batch_size * 5) == 0 or done >= len(items):
            log(f"  {done}/{len(items)} fragmenten ingebed")

    SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)
    flat = array("f", [value for vector in vectors for value in vector])
    VECTORS_PATH.write_bytes(flat.tobytes())
    meta = {
        "model": model,
        "dim": dim,
        "count": len(vectors),
        "built_at": _now(),
        "source_signature": _source_signature(),
        "items": [{key: value for key, value in item.items() if key != "text"} for item in items],
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    clear_index_cache()
    log(f"Semantische index geschreven: {len(vectors)} vectoren van {dim} dimensies -> {_display_path(VECTORS_PATH)}")
    return {"items": len(items), "vectors": len(vectors), "dim": dim, "model": model, "written": True, "dry_run": False}


_INDEX_CACHE: tuple[tuple[float, int] | None, SemanticIndex | None] = (None, None)


def clear_index_cache() -> None:
    """Drop the cached index (used after a rebuild and by tests)."""
    global _INDEX_CACHE
    _INDEX_CACHE = (None, None)


def index_exists() -> bool:
    """True when a built vector store is present on disk."""
    return VECTORS_PATH.exists() and META_PATH.exists()


def load_semantic_index() -> SemanticIndex | None:
    """Load the vector store once per process, or return None when missing."""
    global _INDEX_CACHE
    if not index_exists():
        return None
    stat = META_PATH.stat()
    key = (stat.st_mtime, stat.st_size)
    if _INDEX_CACHE[0] == key and _INDEX_CACHE[1] is not None:
        return _INDEX_CACHE[1]

    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        raw = VECTORS_PATH.read_bytes()
    except (OSError, ValueError):
        return None

    dim = int(meta.get("dim") or 0)
    items = meta.get("items") or []
    if not dim or not items:
        return None

    uses_numpy = True
    try:
        import numpy as np

        vectors: Any = np.frombuffer(raw, dtype="float32").reshape(-1, dim)
        if vectors.shape[0] != len(items):
            return None
    except ImportError:
        uses_numpy = False
        flat = array("f")
        flat.frombytes(raw)
        if len(flat) != len(items) * dim:
            return None
        vectors = flat

    index = SemanticIndex(
        model=str(meta.get("model") or DEFAULT_EMBED_MODEL),
        dim=dim,
        built_at=str(meta.get("built_at") or ""),
        items=items,
        vectors=vectors,
        source_signature=meta.get("source_signature") or {},
        uses_numpy=uses_numpy,
    )
    _INDEX_CACHE = (key, index)
    return index


def semantic_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[list[dict[str, Any]], str]:
    """Return ``(hits, status)`` for one question.

    ``status`` is a machine-readable reason such as ``no_index``,
    ``embedding_unavailable``, ``no_semantic_match`` or ``semantic_match``.
    """
    index = load_semantic_index()
    if index is None:
        return [], "no_index"
    try:
        vector = embed_texts([query], model=index.model, base_url=base_url)[0]
    except (EmbeddingError, IndexError):
        return [], "embedding_unavailable"

    hits = index.search(_normalize(vector), top_k=top_k, min_score=min_score)
    return hits, "semantic_match" if hits else "no_semantic_match"


def semantic_status() -> dict[str, Any]:
    """Return a small status dict for diagnostics and the UI sidebar."""
    index = load_semantic_index()
    if index is None:
        return {
            "available": False,
            "reason": "no_index",
            "hint": "Bouw de index met: python main.py --build-embeddings",
        }
    return {
        "available": True,
        "model": index.model,
        "items": len(index),
        "dim": index.dim,
        "built_at": index.built_at,
        "stale": index.is_stale(),
        "backend": "numpy" if index.uses_numpy else "pure-python",
    }
