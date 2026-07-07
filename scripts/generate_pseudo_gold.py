#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import NOISE_PHRASES, as_list, stable_id, unique, utc_now_iso, write_jsonl

DEFAULT_CURATED = ROOT / "data/ho_definities_curated.json"
DEFAULT_INDEX = ROOT / "data/ho_definities_index.jsonl"
DEFAULT_CHUNKS = ROOT / "data/chunks.jsonl"
DEFAULT_OUTPUT = ROOT / "data/evaluation/pseudo_gold_questions.jsonl"


def load_curated(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("entries", [])


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def confidence_label(entry: dict[str, Any]) -> str:
    raw = entry.get("confidence", 0.0)
    try: value = float(raw)
    except (TypeError, ValueError): value = 0.0
    text = " ".join(map(str, as_list(entry.get("definition")) + as_list(entry.get("source_fragments")))).lower()
    noisy = any(phrase.lower() in text for phrase in NOISE_PHRASES)
    if value >= 0.8 and not noisy: return "high"
    if value >= 0.5: return "medium"
    return "low"


def key_phrases(definition: str) -> list[str]:
    definition = re.sub(r"\s+", " ", definition).strip()
    if not definition: return []
    phrases = []
    for part in re.split(r"(?<=[.;:])\s+|,\s+", definition):
        part = part.strip(" .;:")
        if 12 <= len(part) <= 120:
            phrases.append(part)
        if len(phrases) >= 2: break
    return phrases or [definition[:120].rstrip()]


def base_case(entry: dict[str, Any], question: str, case_type: str, *, expected_contains=None) -> dict[str, Any]:
    term = str(entry.get("term", "")).strip()
    fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")))
    datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")))
    fragments = [str(x)[:300] for x in as_list(entry.get("source_fragments")) if str(x).strip()]
    return {
        "id": stable_id("pseudo_gold", case_type, question, term),
        "question": question,
        "expected_main_term": term,
        "expected_answer_contains": expected_contains or [],
        "expected_fields": fields if case_type in {"fields", "metadata_cleanliness"} else [],
        "expected_datasets": datasets if case_type in {"datasets", "location", "metadata_cleanliness"} else [],
        "forbidden_answer_contains": NOISE_PHRASES if case_type == "metadata_cleanliness" else [],
        "forbidden_fields": NOISE_PHRASES,
        "forbidden_datasets": ["hoacth.csv", "hoacth_vest.csv", "Inschrijvingen_aggr_UNL_2023.csv"],
        "expected_curated_definition_found": True,
        "source_documents": unique(as_list(entry.get("source_documents"))),
        "source_fragments": fragments,
        "label_status": "pseudo_generated",
        "confidence": confidence_label(entry),
        "case_type": case_type,
        "tags": unique([case_type] + as_list(entry.get("tags"))),
        "created_by": "generate_pseudo_gold.py",
        "last_updated": utc_now_iso(),
    }


def generate_cases(curated: list[dict[str, Any]], index_rows=None, chunks=None) -> list[dict[str, Any]]:
    cases = []
    for entry in curated:
        term = str(entry.get("term", "")).strip()
        definition = str(entry.get("definition", "")).strip()
        fragments = as_list(entry.get("source_fragments"))
        if not term or not fragments:
            continue
        conf = confidence_label(entry)
        if conf == "low":
            continue
        if definition:
            for q in (f"wat is {term}?", f"wat betekent {term}?"):
                cases.append(base_case(entry, q, "definition", expected_contains=key_phrases(definition)))
        fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")))
        if fields:
            cases.append(base_case(entry, f"welke velden horen bij {term}?", "fields"))
        datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")))
        if datasets:
            cases.append(base_case(entry, f"waar vind ik data over {term}?", "location"))
            cases.append(base_case(entry, f"in welke bestanden staat {term}?", "datasets"))
        for alias in unique(as_list(entry.get("aliases")))[:3]:
            cases.append(base_case(entry, f"wat is {alias}?", "alias_canonicalisation", expected_contains=key_phrases(definition)))
        source_text = " ".join(map(str, fragments))
        if re.search(r"\b\d+\s*=|\bcode\b|mogelijke waarden", source_text, flags=re.I):
            cases.append(base_case(entry, f"welke waarden of codes horen bij {term}?", "value_code"))
        if as_list(entry.get("source_terms")) or as_list(entry.get("note")):
            cases.append(base_case(entry, f"welke begrippen zijn gerelateerd aan {term}?", "related_terms"))
        cases.append(base_case(entry, f"is de metadata voor {term} schoon?", "metadata_cleanliness"))
    cases.sort(key=lambda c: c["id"])
    return cases


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args(argv)
    cases = generate_cases(load_curated(args.curated), load_jsonl(args.index), load_jsonl(args.chunks))
    write_jsonl(args.output, cases)
    print(f"Wrote {len(cases)} pseudo-gold evaluation cases to {args.output}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
