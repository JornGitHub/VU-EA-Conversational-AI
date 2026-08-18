"""Shared text primitives for retrieval: normalisation, tokenising, canonical terms.

These helpers used to live in ``search.py``. They are extracted so that the
corpus cache in ``corpus.py`` can precompute the same features without importing
the whole retrieval module. Behaviour is unchanged; ``search.py`` re-exports
every name it used before.
"""

from __future__ import annotations

import re
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


def normalize_text(text: Any) -> str:
    """Normalize text for matching while preserving Dutch accented letters."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", str(text).lower())).strip()


def singularize_token(token: str) -> str:
    """Very small Dutch-ish singularization helper for query/term matching."""
    if len(token) > 4 and token.endswith("en"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: Any, *, remove_stopwords: bool = True) -> list[str]:
    tokens = [singularize_token(token) for token in normalize_text(text).split()]
    if remove_stopwords:
        tokens = [token for token in tokens if token and token not in STOPWORDS]
    return tokens


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
