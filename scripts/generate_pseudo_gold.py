#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, re, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import NOISE_PHRASES, as_list, stable_id, unique, write_jsonl

DEFAULT_CURATED = ROOT / "data/ho_definities_curated.json"
DEFAULT_INDEX = ROOT / "data/ho_definities_index.jsonl"
DEFAULT_CHUNKS = ROOT / "data/chunks.jsonl"
DEFAULT_OUTPUT = ROOT / "data/evaluation/pseudo_gold_questions.jsonl"

BAD_TERMS = {"bronnen", "mogelijke waarden", "mogelijke waarden her1 her8"}
TERM_FILE_RE = re.compile(r"\.(?:txt|pdf|docx?|csv|asc|xlsx|jsonl?)$", re.I)
DEFINITION_NOISE_RE = re.compile(r"\bEx1\s*=\s*k\b|\bExgf\b|Ex\[t\+1\]|Mogelijke waarden|1\. Inleiding|Het bestand", re.I)
CODE_PAIR_RE = re.compile(r"(?:waarde\s*)?(?P<value>\d{1,3}|[A-Z]{1,4})\s*[=:–-]\s*(?P<meaning>[^.;\n]{4,120})", re.I)
DATASET_RE = re.compile(r"\b[\w*().'-]+\.(?:csv|asc|txt|xlsx|jsonl?|pdf)\b", re.I)


def load_curated(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("entries", [])


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def clean_term(term: Any) -> str:
    return re.sub(r"\s+", " ", str(term or "")).strip()


def is_bad_term(term: Any) -> bool:
    term = clean_term(term)
    norm = re.sub(r"[^\w]+", " ", term.lower()).strip()
    return (
        not term
        or norm in BAD_TERMS
        or norm.startswith("mogelijke waarden")
        or "geeft aan" in norm
        or (norm.startswith("masterex") and len(norm.split()) > 1)
        or len(term) > 90
    )


def is_real_source_document(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and TERM_FILE_RE.search(text))


def source_trace(entry: dict[str, Any], term: str) -> tuple[list[str], list[str]]:
    docs = unique([v for v in as_list(entry.get("source_documents")) + as_list(entry.get("source_document")) if is_real_source_document(v)])
    terms = unique([v for v in as_list(entry.get("source_terms")) + as_list(entry.get("source_documents")) if not is_real_source_document(v)])
    terms = [v for v in terms if str(v).strip() and str(v).strip() != term]
    return docs, terms


def has_definition_noise(text: str) -> bool:
    if DEFINITION_NOISE_RE.search(text):
        return True
    if len(re.findall(r"\b\w{1,8}\s*=", text)) >= 4:
        return True
    return False


def confidence_label(entry: dict[str, Any]) -> str:
    raw = entry.get("confidence", 0.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    text = " ".join(map(str, as_list(entry.get("definition")) + as_list(entry.get("source_fragments"))))
    if value >= 0.8 and not has_definition_noise(text):
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def key_phrases(definition: str) -> list[str]:
    definition = re.sub(r"\s+", " ", definition).strip()
    if not definition or has_definition_noise(definition):
        return []
    phrases = []
    for part in re.split(r"(?<=[.;:])\s+|,\s+", definition):
        part = part.strip(" .;:")
        if 12 <= len(part) <= 120 and not has_definition_noise(part):
            phrases.append(part)
        if len(phrases) >= 2:
            break
    return phrases


def extract_values(text: str) -> list[dict[str, str]]:
    values = []
    for match in CODE_PAIR_RE.finditer(text):
        meaning = re.sub(r"\s+", " ", match.group("meaning")).strip(" -:;")
        if len(meaning) < 4 or has_definition_noise(meaning):
            continue
        values.append({"value": match.group("value"), "meaning_contains": meaning[:80]})
        if len(values) >= 5:
            break
    return values


def expectation_hash(case: dict[str, Any]) -> str:
    payload = {k: v for k, v in case.items() if k not in {"id", "source_hash", "expectation_hash"}}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def base_case(entry: dict[str, Any], question: str, case_type: str, *, expected_contains=None, label_status=None, confidence=None, extra=None) -> dict[str, Any] | None:
    term = clean_term(entry.get("term"))
    if is_bad_term(term):
        return None
    conf = confidence or confidence_label(entry)
    if conf == "low":
        return None
    status = label_status or ("pseudo_generated" if conf == "high" else "pseudo_uncertain")
    docs, source_terms = source_trace(entry, term)
    if not docs:
        return None
    fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")) + as_list(entry.get("related_field_names")))
    datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")) + as_list(entry.get("dataset_or_file")))
    fragments = [str(x)[:300] for x in as_list(entry.get("source_fragments")) if str(x).strip()]
    if not fragments:
        return None
    case: dict[str, Any] = {
        "id": stable_id("pseudo_gold", case_type, question, term),
        "question": question,
        "expected_main_term": term,
        "expected_answer_contains": expected_contains or [],
        "expected_fields": fields if case_type in {"fields", "metadata_cleanliness"} else [],
        "expected_datasets": datasets if case_type in {"datasets", "location", "metadata_cleanliness"} else [],
        "forbidden_answer_contains": NOISE_PHRASES if case_type == "metadata_cleanliness" else [],
        "forbidden_fields": NOISE_PHRASES,
        "forbidden_datasets": ["hoacth.csv", "hoacth_vest.csv", "Inschrijvingen_aggr_UNL_2023.csv"],
        "expected_curated_definition_found": status == "pseudo_generated",
        "source_documents": docs,
        "source_terms": source_terms,
        "source_fragments": fragments,
        "label_status": status,
        "confidence": conf,
        "needs_human_review": status == "pseudo_uncertain",
        "case_type": case_type,
        "tags": unique([case_type] + as_list(entry.get("tags"))),
        "created_by": "generate_pseudo_gold.py",
    }
    if extra:
        case.update(extra)
    case["source_hash"] = hashlib.sha1("\n".join(fragments).encode("utf-8")).hexdigest()[:16]
    case["expectation_hash"] = expectation_hash(case)
    return case


def cases_for_entry(entry: dict[str, Any], *, allow_uncertain: bool = True) -> list[dict[str, Any]]:
    term = clean_term(entry.get("term"))
    definition = str(entry.get("definition", "")).strip()
    if is_bad_term(term):
        return []
    conf = confidence_label(entry)
    if conf == "low" or (conf == "medium" and not allow_uncertain):
        return []
    cases: list[dict[str, Any]] = []
    phrases = key_phrases(definition)
    if phrases and conf == "high":
        for q in (f"wat is {term}?", f"wat betekent {term}?"):
            case = base_case(entry, q, "definition", expected_contains=phrases, confidence=conf)
            if case:
                cases.append(case)
    fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")) + as_list(entry.get("related_field_names")))
    if fields:
        case = base_case(entry, f"welke velden horen bij {term}?", "fields", confidence=conf)
        if case:
            cases.append(case)
    datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")) + as_list(entry.get("dataset_or_file")))
    if datasets:
        for q, typ in ((f"waar vind ik data over {term}?", "location"), (f"in welke bestanden staat {term}?", "datasets")):
            case = base_case(entry, q, typ, confidence=conf)
            if case:
                cases.append(case)
    if phrases and conf == "high":
        for alias in unique(as_list(entry.get("aliases")))[:3]:
            if not is_bad_term(alias):
                case = base_case(entry, f"wat is {alias}?", "alias_canonicalisation", expected_contains=phrases, confidence=conf)
                if case:
                    cases.append(case)
    source_text = " ".join(map(str, as_list(entry.get("source_fragments")) + [definition]))
    expected_values = extract_values(source_text)
    if expected_values:
        case = base_case(entry, f"welke waarden of codes horen bij {term}?", "value_code", confidence=conf, extra={"expected_values": expected_values})
        if case:
            cases.append(case)
    expected_related = unique(as_list(entry.get("related_terms")) + as_list(entry.get("source_terms")) + as_list(entry.get("note")))
    expected_related = [v for v in expected_related if not is_bad_term(v) and clean_term(v) != term]
    if expected_related:
        case = base_case(entry, f"welke begrippen zijn gerelateerd aan {term}?", "related_terms", confidence=conf, extra={"expected_related_terms": expected_related[:8]})
        if case:
            cases.append(case)
    case = base_case(entry, f"is de metadata voor {term} schoon?", "metadata_cleanliness", confidence=conf)
    if case:
        cases.append(case)
    return cases


def enrich_curated_entries(curated: list[dict[str, Any]], index_rows: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: dict[str, dict[str, list[Any]]] = {}
    for row in index_rows:
        term = clean_term(row.get("term"))
        if is_bad_term(term):
            continue
        bucket = evidence.setdefault(term.lower(), {"source_documents": [], "source_fragments": [], "fields": [], "datasets": []})
        bucket["source_documents"].extend([doc for doc in as_list(row.get("source_documents")) + as_list(row.get("source_document")) if is_real_source_document(doc)])
        bucket["source_fragments"].extend(as_list(row.get("source_fragments")))
        bucket["fields"].extend(as_list(row.get("fields")) + as_list(row.get("related_fields")))
        bucket["datasets"].extend(as_list(row.get("datasets")) + as_list(row.get("available_in_datasets")))
    for chunk in chunks:
        doc = chunk.get("source_document")
        if not is_real_source_document(doc):
            continue
        for term in as_list(chunk.get("terms")):
            term = clean_term(term)
            if is_bad_term(term):
                continue
            bucket = evidence.setdefault(term.lower(), {"source_documents": [], "source_fragments": [], "fields": [], "datasets": []})
            bucket["source_documents"].append(doc)
            bucket["source_fragments"].append(str(chunk.get("text", ""))[:300])
            bucket["fields"].extend(as_list(chunk.get("fields")))
            bucket["datasets"].extend(as_list(chunk.get("datasets")) + DATASET_RE.findall(str(chunk.get("text", ""))))
    enriched = []
    for entry in curated:
        term = clean_term(entry.get("term"))
        merged = dict(entry)
        bucket = evidence.get(term.lower())
        if bucket:
            merged["source_documents"] = unique(as_list(merged.get("source_documents")) + bucket["source_documents"])
            if not as_list(merged.get("source_fragments")):
                merged["source_fragments"] = unique(bucket["source_fragments"])
            merged["fields"] = unique(as_list(merged.get("fields")) + bucket["fields"])
            merged["datasets"] = unique(as_list(merged.get("datasets")) + bucket["datasets"])
        enriched.append(merged)
    return enriched


def entries_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for chunk in chunks:
        doc = chunk.get("source_document")
        if not is_real_source_document(doc):
            continue
        text = str(chunk.get("text", ""))
        datasets = unique(as_list(chunk.get("datasets")) + DATASET_RE.findall(text))
        for term in as_list(chunk.get("terms"))[:5]:
            term = clean_term(term)
            if is_bad_term(term):
                continue
            entries.append({
                "term": term,
                "definition": "",
                "fields": as_list(chunk.get("fields")),
                "datasets": datasets,
                "source_documents": [doc],
                "source_fragments": [text[:300]],
                "confidence": 0.6,
            })
    return entries


def generate_cases(curated: list[dict[str, Any]], index_rows=None, chunks=None, *, include_uncertain: bool = True) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    index_rows = index_rows or []
    chunks = chunks or []
    for entry in enrich_curated_entries(curated, index_rows, chunks):
        cases.extend(cases_for_entry(entry, allow_uncertain=include_uncertain))
    # Use index and chunks for broader field/dataset coverage only as uncertain, never as gateable high confidence.
    for entry in index_rows:
        entry = dict(entry)
        entry["confidence"] = min(float(entry.get("confidence") or 0.0), 0.79)
        cases.extend(cases_for_entry(entry, allow_uncertain=include_uncertain))
    for entry in entries_from_chunks(chunks):
        cases.extend(cases_for_entry(entry, allow_uncertain=include_uncertain))
    by_id = {case["id"]: case for case in cases}
    return sorted(by_id.values(), key=lambda c: c["id"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--no-uncertain", action="store_true", help="Only write clean high-confidence gate cases.")
    args = p.parse_args(argv)
    cases = generate_cases(load_curated(args.curated), load_jsonl(args.index), load_jsonl(args.chunks), include_uncertain=not args.no_uncertain)
    write_jsonl(args.output, cases)
    print(f"Wrote {len(cases)} pseudo-gold evaluation cases to {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
