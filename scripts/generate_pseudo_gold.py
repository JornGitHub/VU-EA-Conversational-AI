#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, re, sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import NOISE_PHRASES, as_list, read_jsonl, stable_id, unique, write_jsonl
from scripts.run_evaluation import evaluate_case
from src.definitions.search import answer_definition_question_json

DEFAULT_CURATED = ROOT / "data/ho_definities_curated.json"
DEFAULT_INDEX = ROOT / "data/ho_definities_index.jsonl"
DEFAULT_CHUNKS = ROOT / "data/chunks.jsonl"
DEFAULT_EVAL_DIR = ROOT / "data/evaluation"
DEFAULT_PSEUDO_GOLD = DEFAULT_EVAL_DIR / "pseudo_gold_questions.jsonl"
DEFAULT_PSEUDO_CANDIDATES = DEFAULT_EVAL_DIR / "pseudo_candidate_questions.jsonl"
DEFAULT_GOLD_CORE = DEFAULT_EVAL_DIR / "gold_core_questions.jsonl"
DEFAULT_OVERRIDES = DEFAULT_EVAL_DIR / "developer_feedback_overrides.jsonl"

BAD_TERMS = {"bronnen", "mogelijke waarden", "mogelijke waarden her1 her8", "records", "lay", "aarden"}
GENERIC_SINGLE_WORDS = BAD_TERMS | {"waarden", "variabelen", "gegevens", "bestand", "bestanden", "records"}
TERM_FILE_RE = re.compile(r"\.(?:txt|pdf|docx?|csv|asc|xlsx|jsonl?)$", re.I)
DEFINITION_NOISE_RE = re.compile(r"\bEx1\s*=\s*k\b|\bExgf\b|Ex\[t\+1\]|Mogelijke waarden|1\. Inleiding|Het bestand", re.I)
DATASET_NOISE_RE = re.compile(r"1\. Inleiding|Het bestand|nationaliteit is onbekend|geboorteland is onbekend|Zie bestand|Mogelijke waarden", re.I)
PROSE_TERM_RE = re.compile(r"komt overeen met|gaat in principe|vorige leveringen|ten opzichte van", re.I)
DATASET_RE = re.compile(r"\b[\w*().'-]+\.(?:csv|asc|txt|xlsx|jsonl?|pdf|docx?)\b", re.I)
CODE_PAIR_RE = re.compile(r"(?:waarde|code)?\s*(?P<value>\d{1,3}|J|N|wo|hbo|ba|ma|ad)\s*[=:–-]\s*(?P<meaning>[^.;\n]{4,120})", re.I)
HELPER_DATASETS = {"hoacth.csv", "hoacth_vest.csv", "dec_nationaliteitscode.csv", "dec_landcode.csv", "dec_vopl.asc"}
OLD_YEAR_DATASET_RE = re.compile(r"(?:^|_)(?:20[0-2][0-4])\.", re.I)
PROHIBITED_STARTS = ("de ", "het ", "een ", "anders ", "vanaf ", "ten opzichte ")
KNOWN_LOWERCASE_TERMS = {"wo", "hbo", "ba", "ma", "ad"}
KNOWN_CODES = {"j", "n", "wo", "hbo", "ba", "ma", "ad"}


def load_curated(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("entries", [])


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def clean_term(term: Any) -> str:
    return re.sub(r"\s+", " ", str(term or "")).strip()


def term_reject_reason(term: Any) -> str | None:
    term = clean_term(term)
    norm = re.sub(r"[^\w]+", " ", term.lower()).strip()
    words = norm.split()
    if not term:
        return "empty_term"
    if re.search(r"-{5,}", term):
        return "separator_dashes"
    if len(term) < 3:
        return "too_short_term"
    if norm in BAD_TERMS or (len(words) == 1 and norm in GENERIC_SINGLE_WORDS):
        return "generic_term"
    if norm.startswith("mogelijke waarden"):
        return "generic_term"
    if term[0].islower() and norm not in KNOWN_LOWERCASE_TERMS:
        return "lowercase_fragment"
    if len(words) > 8:
        return "sentence_like_term"
    if norm.startswith(PROHIBITED_STARTS):
        return "sentence_like_term"
    if "geeft aan" in norm or PROSE_TERM_RE.search(term):
        return "sentence_like_term"
    if norm.startswith("masterex") and len(words) > 1:
        return "sentence_like_term"
    if len(term) > 90:
        return "sentence_like_term"
    return None


def is_bad_term(term: Any) -> bool:
    return term_reject_reason(term) is not None


def term_quality_warnings(term: Any) -> list[str]:
    reason = term_reject_reason(term)
    return [reason] if reason else []


def is_real_source_document(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and TERM_FILE_RE.search(text))


def source_trace(entry: dict[str, Any], term: str) -> tuple[list[str], list[str]]:
    docs = unique([v for v in as_list(entry.get("source_documents")) + as_list(entry.get("source_document")) if is_real_source_document(v)])
    terms = unique([v for v in as_list(entry.get("source_terms")) + as_list(entry.get("source_documents")) if not is_real_source_document(v)])
    terms = [v for v in terms if str(v).strip() and str(v).strip() != term]
    return docs, terms


def has_definition_noise(text: str) -> bool:
    return bool(DEFINITION_NOISE_RE.search(text) or len(re.findall(r"\b\w{1,8}\s*=", text)) >= 4)


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


def sanitize_dataset_values(values: list[Any], *, allow_helpers: bool = False) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    cleaned: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            continue
        if DATASET_NOISE_RE.search(text) or len(text) > 120:
            warnings.append("prose_dataset_fragment")
        filenames = DATASET_RE.findall(text) if (DATASET_NOISE_RE.search(text) or len(text) > 80) else [text]
        for filename in filenames:
            filename = filename.strip(" ,.;:()[]")
            lower = filename.lower()
            if not DATASET_RE.fullmatch(filename):
                continue
            if lower in HELPER_DATASETS or lower.startswith("dec_"):
                warnings.append("helper_decoder_dataset")
                if not allow_helpers:
                    continue
            if OLD_YEAR_DATASET_RE.search(filename):
                warnings.append("old_year_dataset")
                continue
            cleaned.append(filename)
    return unique(cleaned), unique(warnings)


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


def value_quality_warning(value: str, meaning: str) -> str | None:
    value_norm = value.lower()
    if value_norm.isdigit():
        if not 1 <= int(value_norm) <= 999:
            return "suspicious_value_code"
    elif value_norm not in KNOWN_CODES:
        return "suspicious_value_code"
    if len(value) == 1 and value_norm not in KNOWN_CODES and not value_norm.isdigit():
        return "suspicious_value_code"
    if meaning.lower() in {"oegd", "nnen", "esco"} or len(meaning.split()) > 14 or len(meaning) < 4:
        return "suspicious_value_code"
    if re.search(r"\b(?:UNESCO|CBS-indeling|komt overeen met)\b", meaning, re.I):
        return "suspicious_value_code"
    return None


def extract_values(text: str) -> tuple[list[dict[str, str]], list[str]]:
    values = []
    warnings: list[str] = []
    for match in CODE_PAIR_RE.finditer(text):
        value = match.group("value")
        meaning = re.sub(r"\s+", " ", match.group("meaning")).strip(" -:;")
        warning = value_quality_warning(value, meaning)
        if warning:
            warnings.append(warning)
            continue
        values.append({"value": value, "meaning_contains": meaning[:80]})
        if len(values) >= 5:
            break
    return values, unique(warnings)


def expectation_hash(case: dict[str, Any]) -> str:
    payload = {k: v for k, v in case.items() if k not in {"id", "source_hash", "expectation_hash"}}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def add_hashes(case: dict[str, Any]) -> dict[str, Any]:
    fragments = [str(x) for x in as_list(case.get("source_fragments"))]
    case["source_hash"] = hashlib.sha1("\n".join(fragments).encode("utf-8")).hexdigest()[:16]
    case["expectation_hash"] = expectation_hash(case)
    return case


def candidate_warnings(term: str, datasets: list[str], value_warnings: list[str], extra: list[str] | None = None) -> list[str]:
    warnings = term_quality_warnings(term) + value_warnings + (extra or [])
    for dataset in datasets:
        if dataset.lower() in HELPER_DATASETS or dataset.lower().startswith("dec_"):
            warnings.append("helper_decoder_dataset")
        if OLD_YEAR_DATASET_RE.search(dataset):
            warnings.append("old_year_dataset")
    return unique(warnings)


def base_case(entry: dict[str, Any], question: str, case_type: str, *, expected_contains=None, confidence=None, extra=None, extraction_reason="curated_enriched", stats: Counter | None = None) -> dict[str, Any] | None:
    term = clean_term(entry.get("term"))
    reason = term_reject_reason(term)
    if reason:
        if stats is not None:
            stats[f"rejected_{reason}"] += 1
        return None
    conf = confidence or confidence_label(entry)
    if conf == "low":
        if stats is not None:
            stats["rejected_low_confidence"] += 1
        return None
    docs, source_terms = source_trace(entry, term)
    if not docs:
        if stats is not None:
            stats["rejected_missing_source_document"] += 1
        return None
    raw_datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")) + as_list(entry.get("dataset_or_file")))
    datasets, dataset_warnings = sanitize_dataset_values(raw_datasets)
    fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")) + as_list(entry.get("related_field_names")))
    fragments = [str(x)[:300] for x in as_list(entry.get("source_fragments")) if str(x).strip()]
    if not fragments:
        if stats is not None:
            stats["rejected_missing_source_fragment"] += 1
        return None
    status = "pseudo_generated" if conf == "high" else "pseudo_uncertain"
    value_warnings: list[str] = []
    if extra and extra.get("candidate_quality_warnings"):
        value_warnings = as_list(extra.get("candidate_quality_warnings"))
    warnings = candidate_warnings(term, datasets, value_warnings, dataset_warnings)
    gate_blocking_warnings = term_quality_warnings(term) + value_warnings
    if status == "pseudo_generated" and gate_blocking_warnings:
        if stats is not None:
            stats["rejected_high_confidence_warnings"] += 1
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
    if status == "pseudo_uncertain":
        case["candidate_quality_warnings"] = warnings
        case["extraction_reason"] = extraction_reason
    if extra:
        case.update({k: v for k, v in extra.items() if k != "candidate_quality_warnings"})
    return add_hashes(case)


def cases_for_entry(entry: dict[str, Any], *, extraction_reason: str, stats: Counter) -> list[dict[str, Any]]:
    term = clean_term(entry.get("term"))
    definition = str(entry.get("definition", "")).strip()
    if term_reject_reason(term):
        stats[f"rejected_{term_reject_reason(term)}"] += 1
        return []
    conf = confidence_label(entry)
    if conf == "low":
        stats["rejected_low_confidence"] += 1
        return []
    cases: list[dict[str, Any]] = []
    phrases = key_phrases(definition)
    if phrases and conf == "high":
        for q in (f"wat is {term}?", f"wat betekent {term}?"):
            case = base_case(entry, q, "definition", expected_contains=phrases, confidence=conf, extraction_reason=extraction_reason, stats=stats)
            if case:
                cases.append(case)
    fields = unique(as_list(entry.get("fields")) + as_list(entry.get("related_fields")) + as_list(entry.get("related_field_names")))
    if fields:
        case = base_case(entry, f"welke velden horen bij {term}?", "fields", confidence=conf, extraction_reason=extraction_reason, stats=stats)
        if case:
            cases.append(case)
    raw_datasets = unique(as_list(entry.get("datasets")) + as_list(entry.get("available_in_datasets")) + as_list(entry.get("dataset_or_file")))
    datasets, _warnings = sanitize_dataset_values(raw_datasets)
    if datasets:
        for q, typ in ((f"waar vind ik data over {term}?", "location"), (f"in welke bestanden staat {term}?", "datasets")):
            case = base_case(entry, q, typ, confidence=conf, extraction_reason=extraction_reason, stats=stats)
            if case:
                cases.append(case)
    if phrases and conf == "high":
        for alias in unique(as_list(entry.get("aliases")))[:3]:
            case = base_case(entry, f"wat is {alias}?", "alias_canonicalisation", expected_contains=phrases, confidence=conf, extraction_reason=extraction_reason, stats=stats)
            if case:
                cases.append(case)
    source_text = " ".join(map(str, as_list(entry.get("source_fragments")) + [definition]))
    expected_values, value_warnings = extract_values(source_text)
    if expected_values:
        case = base_case(entry, f"welke waarden of codes horen bij {term}?", "value_code", confidence=conf, extraction_reason=extraction_reason, extra={"expected_values": expected_values, "candidate_quality_warnings": value_warnings}, stats=stats)
        if case:
            cases.append(case)
    elif value_warnings:
        stats["rejected_suspicious_value_code"] += 1
    expected_related = unique(as_list(entry.get("related_terms")) + as_list(entry.get("source_terms")) + as_list(entry.get("note")))
    expected_related = [v for v in expected_related if not term_reject_reason(v) and clean_term(v) != term]
    if expected_related:
        case = base_case(entry, f"welke begrippen zijn gerelateerd aan {term}?", "related_terms", confidence=conf, extraction_reason=extraction_reason, extra={"expected_related_terms": expected_related[:8]}, stats=stats)
        if case:
            cases.append(case)
    case = base_case(entry, f"is de metadata voor {term} schoon?", "metadata_cleanliness", confidence=conf, extraction_reason=extraction_reason, stats=stats)
    if case:
        cases.append(case)
    return cases


def enrich_curated_entries(curated: list[dict[str, Any]], index_rows: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: dict[str, dict[str, list[Any]]] = {}
    for row in index_rows:
        term = clean_term(row.get("term"))
        if term_reject_reason(term):
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
            if term_reject_reason(term):
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
        merged["extraction_reason"] = "curated_enriched"
        bucket = evidence.get(term.lower())
        if bucket:
            merged["source_documents"] = unique(as_list(merged.get("source_documents")) + bucket["source_documents"])
            if not as_list(merged.get("source_fragments")):
                merged["source_fragments"] = unique(bucket["source_fragments"])
            merged["fields"] = unique(as_list(merged.get("fields")) + bucket["fields"])
            merged["datasets"] = unique(as_list(merged.get("datasets")) + bucket["datasets"])
        enriched.append(merged)
    return enriched


def entries_from_chunks(chunks: list[dict[str, Any]], stats: Counter) -> list[dict[str, Any]]:
    entries = []
    for chunk in chunks:
        doc = chunk.get("source_document")
        if not is_real_source_document(doc):
            stats["rejected_missing_source_document"] += 1
            continue
        text = str(chunk.get("text", ""))
        datasets = unique(as_list(chunk.get("datasets")) + DATASET_RE.findall(text))
        for term in as_list(chunk.get("terms"))[:5]:
            term = clean_term(term)
            reason = term_reject_reason(term)
            if reason:
                stats[f"rejected_{reason}"] += 1
                continue
            entries.append({
                "term": term,
                "definition": "",
                "fields": as_list(chunk.get("fields")),
                "datasets": datasets,
                "source_documents": [doc],
                "source_fragments": [text[:300]],
                "confidence": 0.6,
                "extraction_reason": "chunk",
            })
    return entries


def append_warning(case: dict[str, Any], warning: str) -> None:
    warnings = list(as_list(case.get("candidate_quality_warnings")))
    if warning not in warnings:
        warnings.append(warning)
    case["candidate_quality_warnings"] = warnings


def demote_to_candidate(case: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    demoted = dict(case)
    demoted["label_status"] = "pseudo_uncertain"
    demoted["confidence"] = "medium"
    demoted["needs_human_review"] = True
    demoted["extraction_reason"] = demoted.get("extraction_reason") or "demoted_executable"
    demoted["executable_failures"] = failures
    append_warning(demoted, "executable_expectation_failed")
    return add_hashes(demoted)


def split_tiers(cases: list[dict[str, Any]], answer_func=answer_definition_question_json) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {case["id"]: case for case in cases}
    all_cases = sorted(by_id.values(), key=lambda c: c["id"])
    pseudo_gold: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for case in all_cases:
        if case.get("label_status") == "pseudo_generated":
            actual = answer_func(str(case.get("question", "")))
            failures = evaluate_case(case, actual)
            if failures:
                candidates.append(demote_to_candidate(case, failures))
            else:
                pseudo_gold.append(case)
        elif case.get("label_status") == "pseudo_uncertain":
            candidates.append(case)
    return pseudo_gold, candidates


def generate_case_tiers(curated: list[dict[str, Any]], index_rows=None, chunks=None, *, answer_func=answer_definition_question_json) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    stats: Counter = Counter()
    cases: list[dict[str, Any]] = []
    index_rows = index_rows or []
    chunks = chunks or []
    for entry in enrich_curated_entries(curated, index_rows, chunks):
        cases.extend(cases_for_entry(entry, extraction_reason=entry.get("extraction_reason", "curated_enriched"), stats=stats))
    for entry in index_rows:
        entry = dict(entry)
        entry["confidence"] = min(float(entry.get("confidence") or 0.0), 0.79)
        entry["extraction_reason"] = "index_row"
        cases.extend(cases_for_entry(entry, extraction_reason="index_row", stats=stats))
    for entry in entries_from_chunks(chunks, stats):
        cases.extend(cases_for_entry(entry, extraction_reason="chunk", stats=stats))
    pseudo_gold, candidates = split_tiers(cases, answer_func=answer_func)
    return pseudo_gold, candidates, stats


def generate_cases(curated: list[dict[str, Any]], index_rows=None, chunks=None, *, include_uncertain: bool = True, answer_func=answer_definition_question_json) -> list[dict[str, Any]]:
    pseudo_gold, candidates, _stats = generate_case_tiers(curated, index_rows, chunks, answer_func=answer_func)
    return pseudo_gold + (candidates if include_uncertain else [])


def merge_gold_core(pseudo_gold: list[dict[str, Any]], overrides_path: Path) -> list[dict[str, Any]]:
    by_question = {re.sub(r"\s+", " ", row.get("question", "").lower()).strip(): row for row in pseudo_gold}
    for override in read_jsonl(overrides_path):
        override["label_status"] = override.get("label_status") or "developer_corrected"
        by_question[re.sub(r"\s+", " ", override.get("question", "").lower()).strip()] = override
    return sorted(by_question.values(), key=lambda row: row.get("id", ""))


def print_summary(pseudo_gold: list[dict[str, Any]], candidates: list[dict[str, Any]], gold_core: list[dict[str, Any]], stats: Counter) -> None:
    print("Pseudo-gold generation summary")
    print(f"- pseudo_gold cases: {len(pseudo_gold)}")
    print(f"- pseudo_candidate cases: {len(candidates)}")
    print(f"- gold_core cases: {len(gold_core)}")
    print("- rejected cases by reason:")
    for reason, count in sorted(stats.items()):
        print(f"  - {reason}: {count}")
    suspicious = [c.get("expected_main_term") for c in candidates if c.get("candidate_quality_warnings")][:10]
    print("- examples of rejected/suspicious terms:")
    for term in suspicious:
        print(f"  - {term}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    p.add_argument("--pseudo-gold-output", type=Path, default=DEFAULT_PSEUDO_GOLD)
    p.add_argument("--candidate-output", type=Path, default=DEFAULT_PSEUDO_CANDIDATES)
    p.add_argument("--gold-core-output", type=Path, default=DEFAULT_GOLD_CORE)
    p.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = p.parse_args(argv)
    pseudo_gold, candidates, stats = generate_case_tiers(load_curated(args.curated), load_jsonl(args.index), load_jsonl(args.chunks))
    gold_core = merge_gold_core(pseudo_gold, args.overrides)
    write_jsonl(args.pseudo_gold_output, pseudo_gold)
    write_jsonl(args.candidate_output, candidates)
    write_jsonl(args.gold_core_output, gold_core)
    print_summary(pseudo_gold, candidates, gold_core, stats)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
