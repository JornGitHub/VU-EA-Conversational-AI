"""Build evidence-first context packs for deep source-aware answers."""
from __future__ import annotations

from typing import Any

from src.definitions.reference_resolver import resolve_references


def field_summary(field: dict[str, Any]) -> dict[str, Any]:
    keys = ["field_number", "field_name", "description", "dataset", "source_document", "source_path", "bron", "type_field", "possible_values", "notes", "references", "transformations", "related_fields"]
    return {key: field.get(key) for key in keys}


def build_context_pack(query: str, fields: list[dict[str, Any]], *, include_supplemental: bool = True) -> dict[str, Any]:
    references = sorted({ref for field in fields for ref in (field.get("references") or [])}, key=str.lower)
    resolved = resolve_references(references, query=query) if include_supplemental and references else {"resolved_references": [], "supplemental_context": [], "supplemental_sources_used": [], "missing_references": references if references else []}
    return {
        "primary_fields": [field_summary(field) for field in fields],
        "primary_evidence": [
            {
                "source_document": field.get("source_document"),
                "source_path": field.get("source_path"),
                "text": f"{field.get('field_name')}: {field.get('description')}",
                "references": field.get("references", []),
            }
            for field in fields
        ],
        **resolved,
    }
