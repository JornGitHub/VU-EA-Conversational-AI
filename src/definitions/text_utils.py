"""Shared text primitives for retrieval: normalisation, tokenising, canonical terms.

These helpers used to live in ``search.py``. They are extracted so that the
corpus cache in ``corpus.py`` can precompute the same features without importing
the whole retrieval module. Behaviour is unchanged; ``search.py`` re-exports
every name it used before.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

Entry = dict[str, Any]

CANONICAL_TERM_ALIASES = {
    "internationale studenten": "Internationale student",
    "internationale student": "Internationale student",
    "eer studenten": "EER-student",
    "eer student": "EER-student",
    "eer-studenten": "EER-student",
    "eer-student": "EER-student",
}

STOPWORDS = {
    "als",
    "data",
    "de",
    "een",
    "en",
    "er",
    "het",
    "ik",
    "in",
    "is",
    "over",
    "te",
    "telt",
    "van",
    "waar",
    "wat",
    "wie",
    "vind",
    "voor",
    "betekent",
    "definitie",
    "wordt",
    "wanneer",
    "welke",
    "welk",
    "bestand",
    "bestanden",
    "dataset",
}

# Fields that make up the searchable haystack of an entry.
SEARCHABLE_FIELDS = (
    "term",
    "definition",
    "aliases",
    "source_terms",
    "related_fields",
    "related_field_names",
    "available_in_datasets",
    "tags",
    "source_terms",
    "field_name",
    "dataset_or_file",
    "text",
    "source_document",
)


@lru_cache(maxsize=100_000)
def _normalize_cached(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text.lower())).strip()


def normalize_text(text: Any) -> str:
    """Normalize text for matching while preserving Dutch accented letters.

    Cached: answering one question normalizes the same field names and terms
    tens of thousands of times, and the corpus does not change between calls.
    """
    return _normalize_cached(text if isinstance(text, str) else str(text))


@lru_cache(maxsize=100_000)
def singularize_token(token: str) -> str:
    """Very small Dutch-ish singularization helper for query/term matching."""
    if len(token) > 4 and token.endswith("en"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


@lru_cache(maxsize=50_000)
def _tokenize_cached(text: str, remove_stopwords: bool) -> tuple[str, ...]:
    tokens = [singularize_token(token) for token in _normalize_cached(text).split()]
    if remove_stopwords:
        tokens = [token for token in tokens if token and token not in STOPWORDS]
    return tuple(tokens)


def tokenize(text: Any, *, remove_stopwords: bool = True) -> list[str]:
    """Return tokens for matching.

    A list, because callers mutate what they get back; the cache holds the
    immutable tuple behind it.
    """
    source = text if isinstance(text, str) else str(text)
    return list(_tokenize_cached(source, remove_stopwords))


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def canonical_term(term: Any) -> str:
    """Return the protected/canonical display term for known source variants."""
    raw = str(term or "").strip()
    return CANONICAL_TERM_ALIASES.get(normalize_text(raw), raw)


def canonical_aliases_for(entry: Entry) -> list[str]:
    """Return configured aliases when an entry is already the canonical term."""
    term = str(entry.get("term", ""))
    canonical = canonical_term(term)
    aliases = list(as_list(entry.get("aliases")))
    if normalize_text(term) == normalize_text(canonical):
        aliases.extend(
            alias
            for alias, target in CANONICAL_TERM_ALIASES.items()
            if normalize_text(target) == normalize_text(canonical)
        )
    return unique_preserve_order(aliases)


def canonical_preference(entry: Entry) -> int:
    """Prefer protected canonical terms over plural/source variants."""
    term = str(entry.get("term", ""))
    canonical = canonical_term(term)
    if normalize_text(term) == normalize_text(canonical) and canonical:
        return 1
    return 0


def entry_search_text(entry: Entry) -> str:
    """Concatenate the searchable fields of an entry into one haystack string."""
    return " ".join(str(entry.get(field, "")) for field in SEARCHABLE_FIELDS)


# Phrases that only occur in file-layout tables, not in definitions. A curated
# definition that starts with one of these is a dumped table, not an answer.
LAYOUT_DUMP_MARKERS = (
    "lay out bestand",
    "layout bestand",
    "variabele nummer",
    "naam veld bron",
    "type veld",
    "bestandsbeschrijving lay out",
)
MAX_DIGIT_RATIO = 0.15
MIN_LENGTH_FOR_DIGIT_RULE = 200


def looks_like_layout_dump(text: Any) -> bool:
    """Return True when a "definition" is really a dumped layout/field table.

    The 1cHO documents contain large field-layout tables. Text extraction can
    turn such a table into one long paragraph that then looks like a definition
    of whatever term stood above it. Those are never usable answers.
    """
    raw = str(text or "")
    if not raw.strip():
        return False
    normalized = normalize_text(raw)
    if any(marker in normalized for marker in LAYOUT_DUMP_MARKERS):
        return True
    if len(raw) >= MIN_LENGTH_FOR_DIGIT_RULE:
        digits = sum(character.isdigit() for character in raw)
        if digits / len(raw) > MAX_DIGIT_RATIO:
            return True
    return False
