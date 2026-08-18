"""Cached corpus loading and precomputed scoring features.

The retrieval layer used to re-read ``ho_definities_curated.json``,
``ho_definities_index.jsonl`` and ``chunks.jsonl`` from disk on every question,
and to re-derive the same normalised strings for every entry on every question.
This module loads each file once per process, keyed on path/mtime/size so an
edited or rebuilt data file is picked up automatically, and precomputes the text
features the scorer needs.

The precomputed values are exactly what the scorer computed before:

* ``haystack``      -> ``normalize_text(entry_search_text(entry))``
* ``term_tokens``   -> ``set(tokenize(canonical_term(entry["term"])))``
* ``titles``        -> normalised term/alias candidates with their token sets

``filter_blob`` and ``max_title_ratio_bound`` are additions used only to reject
entries that provably score 0, so ranking stays identical.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.definitions.text_utils import (
    Entry,
    canonical_aliases_for,
    canonical_preference,
    canonical_term,
    entry_search_text,
    normalize_text,
    tokenize,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CURATED_PATH = DATA_DIR / "ho_definities_curated.json"
INDEX_PATH = DATA_DIR / "ho_definities_index.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"

CHUNK_DEFINITION_PREVIEW_CHARS = 500


@dataclass(frozen=True)
class TitleCandidate:
    """A term or alias an entry can be matched on, with precomputed features."""

    norm: str
    tokens: frozenset[str]
    length: int


@dataclass
class PreparedEntry:
    """One entry with every text feature the scorer needs already computed."""

    entry: Entry
    source: str
    haystack: str
    term_tokens: frozenset[str]
    titles: tuple[TitleCandidate, ...]
    filter_blob: str
    canonical_preference: int
    static_bonus: float | None = field(default=None, compare=False)


def _file_key(path: Path) -> tuple[str, float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (path.as_posix(), stat.st_mtime, stat.st_size)


def _read_json_entries(path: Path) -> list[Entry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("entries", [])


def _read_jsonl_entries(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _chunk_entry(chunk: Entry) -> Entry:
    return {
        "term": chunk.get("source_document", "Documentfragment"),
        "definition": str(chunk.get("text", ""))[:CHUNK_DEFINITION_PREVIEW_CHARS],
        "source_document": chunk.get("source_document"),
        "source_path": chunk.get("source_path"),
        "page": chunk.get("page"),
        "chunk_id": chunk.get("chunk_id"),
        "entry_type": "chunk",
        "text": chunk.get("text", ""),
    }


_ENTRY_CACHE: dict[str, tuple[tuple[str, float, int] | None, list[Entry]]] = {}


def _cached_entries(name: str, path: Path, loader) -> list[Entry]:
    key = _file_key(path)
    cached = _ENTRY_CACHE.get(name)
    if cached is not None and cached[0] == key:
        return cached[1]
    entries = loader(path)
    _ENTRY_CACHE[name] = (key, entries)
    return entries


def cached_json(path: Path) -> Any:
    """Read and parse a JSON file once per process, re-reading only after edits.

    Used by the field catalog and other small artifacts that were previously
    parsed again for every question.
    """
    return _cached_entries(f"json:{path.as_posix()}", path, lambda p: json.loads(p.read_text(encoding="utf-8")))


def cached_jsonl(path: Path) -> list[Entry]:
    """Read and parse a JSONL file once per process, re-reading only after edits."""
    return _cached_entries(f"jsonl:{path.as_posix()}", path, _read_jsonl_entries)


def load_curated_definitions(path: Path = CURATED_PATH) -> list[Entry]:
    """Load automatically cleaned/high-confidence conversational definitions from data/.

    "Curated" is a legacy file name and does not imply manual approval.
    """
    if path == CURATED_PATH:
        return _cached_entries("curated", path, _read_json_entries)
    return _read_json_entries(path)


def load_index_definitions(path: Path = INDEX_PATH) -> list[Entry]:
    """Load raw field/documentation definitions from JSONL."""
    if path == INDEX_PATH:
        return _cached_entries("index", path, _read_jsonl_entries)
    return _read_jsonl_entries(path)


def load_chunks(path: Path = CHUNKS_PATH) -> list[Entry]:
    """Load offline-generated chunks for optional low-priority fallback search."""
    if path == CHUNKS_PATH:
        return _cached_entries("chunks", path, lambda p: [_chunk_entry(c) for c in _read_jsonl_entries(p)])
    return [_chunk_entry(chunk) for chunk in _read_jsonl_entries(path)]


def prepare_entry(entry: Entry, source: str) -> PreparedEntry:
    """Precompute every text feature the scorer derives from a single entry."""
    haystack = normalize_text(entry_search_text(entry))
    term_tokens = frozenset(tokenize(canonical_term(entry.get("term", ""))))

    titles: list[TitleCandidate] = []
    # The blob is only used to reject entries that cannot score. It must be a
    # superset of every string the scorer looks at: the haystack, the canonical
    # term (which alias mapping can rewrite) and every title candidate.
    blob_parts = [haystack, normalize_text(canonical_term(entry.get("term", "")))]
    for candidate in [entry.get("term", ""), *canonical_aliases_for(entry)]:
        candidate_norm = normalize_text(candidate)
        candidate_tokens = frozenset(tokenize(candidate))
        if not candidate_norm or not candidate_tokens:
            continue
        titles.append(TitleCandidate(candidate_norm, candidate_tokens, len(candidate_norm)))
        blob_parts.append(candidate_norm)

    return PreparedEntry(
        entry=entry,
        source=source,
        haystack=haystack,
        term_tokens=term_tokens,
        titles=tuple(titles),
        filter_blob=" ".join(blob_parts),
        canonical_preference=canonical_preference(entry),
    )


def prepare_entries(entries: Iterable[Entry], source: str) -> list[PreparedEntry]:
    """Prepare a list of entries for one source label."""
    return [prepare_entry(entry, source) for entry in entries]


_PREPARED_CACHE: dict[str, tuple[list[Entry], list[PreparedEntry]]] = {}


def prepared_for(source: str, entries: list[Entry]) -> list[PreparedEntry]:
    """Return prepared entries for one source, reusing the previous preparation.

    The cache holds the entry list object itself, so it is reused exactly while
    the caller keeps handing back the same (cached) list and is rebuilt as soon
    as a loader returns a fresh list because its data file changed.
    """
    cached = _PREPARED_CACHE.get(source)
    if cached is not None and cached[0] is entries:
        return cached[1]
    prepared = prepare_entries(entries, source)
    _PREPARED_CACHE[source] = (entries, prepared)
    return prepared


def prepared_source(source: str) -> list[PreparedEntry]:
    """Return the prepared entries for ``curated``/``index``/``chunk``."""
    loaders = {
        "curated": load_curated_definitions,
        "index": load_index_definitions,
        "chunk": load_chunks,
    }
    if source not in loaders:
        raise ValueError(f"Unknown corpus source: {source}")
    return prepared_for(source, loaders[source]())


def prepared_corpus() -> list[tuple[str, list[PreparedEntry]]]:
    """Return the full default corpus as ``[(source, prepared entries), ...]``."""
    return [(source, prepared_source(source)) for source in ("curated", "index", "chunk")]


def corpus_stats() -> dict[str, Any]:
    """Return entry counts per source, for diagnostics and the UI footer."""
    return {source: len(entries) for source, entries in prepared_corpus()}


def clear_cache() -> None:
    """Drop all cached corpora (used by tests and after a knowledge-base build)."""
    _ENTRY_CACHE.clear()
    _PREPARED_CACHE.clear()
