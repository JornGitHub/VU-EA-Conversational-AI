"""Resolve source-document references from field catalog entries.

References such as hoacth.csv are not primary datasets for answers, but they are
valid evidence targets for supplemental context.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.definitions.corpus import cached_jsonl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
DOCUMENT_REFERENCES_PATH = DATA_DIR / "document_references.json"
SOURCE_ROOTS = [PROJECT_ROOT / "sources", PROJECT_ROOT / "1cHO Documentatie"]

REFERENCE_ALIASES = {
    "hoacth.csv": ["hoacth.csv", "Bestandsbeschrijving hoacth.csv", "hoacth"],
    "hoacth_vest.csv": ["hoacth_vest.csv", "Bestandsbeschrijving hoacth_vest.csv", "hoacth_vest"],
    "Iscedf2013.txt": ["Iscedf2013.txt", "Iscedf2013"],
    "Dec_vopl.csv": ["Dec_vopl.csv", "Dec_vopl", "dec_vopl.asc"],
    "Dec_nationaliteitscode.csv": ["Dec_nationaliteitscode.csv", "Dec_nationaliteitscode", "dec_nationaliteitscode.asc"],
    "dec_landcode.csv": ["dec_landcode.csv", "dec_landcode"],
}


def normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", str(text).lower())).strip()


def reference_aliases(reference: str) -> list[str]:
    return REFERENCE_ALIASES.get(reference, [reference])


@lru_cache(maxsize=256)
def find_reference_files(reference: str) -> list[Path]:
    aliases = [normalize_text(a) for a in reference_aliases(reference)]
    found: list[Path] = []
    for root in SOURCE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            haystack = normalize_text(path.name + " " + path.stem)
            if any(alias and alias in haystack for alias in aliases):
                found.append(path)
    return sorted(set(found), key=lambda p: p.as_posix())


def load_chunks() -> list[dict[str, Any]]:
    """Return all chunks, cached so one deep-context answer reads the file once."""
    return cached_jsonl(CHUNKS_PATH)


def resolve_reference(reference: str, *, query: str = "", limit: int = 3) -> dict[str, Any]:
    files = find_reference_files(reference)
    aliases = [normalize_text(a) for a in reference_aliases(reference)]
    query_tokens = set(normalize_text(query).split())
    chunks = []
    for chunk in load_chunks():
        source_text = normalize_text(f"{chunk.get('source_document','')} {chunk.get('source_path','')}")
        body = normalize_text(chunk.get("text", ""))
        # Only use chunks whose own source document/path matches the reference.
        # Mentions inside the primary document prove the reference exists, but are
        # not supplemental documentation for that reference.
        if any(alias and alias in source_text for alias in aliases):
            score = sum(1 for token in query_tokens if token in body)
            chunks.append({
                "chunk_id": chunk.get("chunk_id"),
                "source_document": chunk.get("source_document"),
                "source_path": chunk.get("source_path"),
                "page": chunk.get("page"),
                "text": str(chunk.get("text", ""))[:900],
                "score": score,
            })
    chunks.sort(key=lambda c: c["score"], reverse=True)
    return {
        "reference": reference,
        "aliases": reference_aliases(reference),
        "found_files": [p.relative_to(PROJECT_ROOT).as_posix() if p.is_relative_to(PROJECT_ROOT) else p.as_posix() for p in files],
        "chunks": chunks[:limit],
        "missing": not files and not chunks,
    }


def resolve_references(references: list[str], *, query: str = "") -> dict[str, Any]:
    resolved = [resolve_reference(ref, query=query) for ref in sorted(set(references), key=str.lower)]
    return {
        "resolved_references": resolved,
        "supplemental_context": [chunk for item in resolved for chunk in item["chunks"]],
        "supplemental_sources_used": sorted({chunk.get("source_document") or chunk.get("source_path") for item in resolved for chunk in item["chunks"] if chunk.get("source_document") or chunk.get("source_path")}),
        "missing_references": [item["reference"] for item in resolved if item["missing"]],
    }


def write_document_references(catalog: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
    mapping = []
    for field in catalog:
        refs = field.get("references") or []
        if refs:
            resolved = resolve_references(refs, query=field.get("field_name", ""))
            mapping.append({
                "field_number": field.get("field_number"),
                "field_name": field.get("field_name"),
                "references": refs,
                "resolved_references": resolved["resolved_references"],
                "missing_references": resolved["missing_references"],
            })
    if not dry_run:
        DATA_DIR.mkdir(exist_ok=True)
        DOCUMENT_REFERENCES_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"fields_with_references": len(mapping), "missing_references": sorted({r for m in mapping for r in m["missing_references"]})}
