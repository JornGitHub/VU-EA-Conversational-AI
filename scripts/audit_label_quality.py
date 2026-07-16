#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation_utils import as_list, read_jsonl, write_jsonl
from scripts.run_evaluation import evaluate_case
from src.definitions.search import answer_definition_question_json

EVAL_DIR = ROOT / "data/evaluation"
DEFAULT_GOLD_CORE = EVAL_DIR / "gold_core_questions.jsonl"
DEFAULT_PSEUDO_GOLD = EVAL_DIR / "pseudo_gold_questions.jsonl"
DEFAULT_PSEUDO_CANDIDATE = EVAL_DIR / "pseudo_candidate_questions.jsonl"
DEFAULT_DEVELOPER_OVERRIDES = EVAL_DIR / "developer_feedback_overrides.jsonl"
DEFAULT_DEVELOPER_CORRECTED = EVAL_DIR / "developer_corrected_questions.jsonl"
DEFAULT_REPORT = EVAL_DIR / "label_quality_report.md"
DEFAULT_REJECTED = EVAL_DIR / "rejected_label_candidates.jsonl"

BAD_TERMS = {"bronnen", "records", "lay", "mogelijke waarden", "toelichting", "inleiding"}
NOISY_ANSWER_RE = re.compile(
    r"Ex1\s*=\s*k|\bExgf\b|Ex\[t\+1\]|Mogelijke waarden|1\. Inleiding|Het bestand|"
    r"nationaliteit is onbekend|geboorteland is onbekend",
    re.I,
)
NOISY_DATASET_RE = re.compile(
    r"1\. Inleiding|Het bestand|nationaliteit is onbekend|geboorteland is onbekend|Zie bestand|Mogelijke waarden",
    re.I,
)
SOURCE_DOCUMENT_RE = re.compile(r"\.(?:txt|docx?|pdf|csv|asc)$", re.I)
DATASET_NAME_RE = re.compile(r"^[\w*().'-]+\.(?:csv|asc|txt|xlsx|jsonl?|pdf|docx?)$", re.I)
HELPER_DATASETS = {"hoacth.csv", "hoacth_vest.csv", "dec_nationaliteitscode.csv", "dec_landcode.csv", "dec_vopl.asc"}


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def term_noise_reason(term: Any) -> str | None:
    text = normalize(term)
    norm = re.sub(r"[^\w]+", " ", text.lower()).strip()
    if not text or len(text) < 3:
        return "noisy_term_too_short"
    if norm in BAD_TERMS or norm.startswith("mogelijke waarden"):
        return "noisy_term_generic"
    if re.search(r"-{5,}", text):
        return "noisy_term_dashes"
    if "geeft aan" in norm or "komt overeen met" in norm:
        return "noisy_term_prose"
    if len(norm.split()) > 8:
        return "noisy_term_sentence_like"
    return None


def answer_noise_reason(snippet: Any) -> str | None:
    text = normalize(snippet)
    if NOISY_ANSWER_RE.search(text):
        return "noisy_answer_snippet"
    if len(re.findall(r"\b\w{1,12}\s*=", text)) >= 4 or (text.count(" - ") >= 5 and len(text) > 160):
        return "noisy_answer_table_row"
    return None


def dataset_noise_reason(dataset: Any, case_type: str | None) -> str | None:
    text = normalize(dataset)
    if not text:
        return "empty_dataset"
    if NOISY_DATASET_RE.search(text):
        return "noisy_dataset_prose"
    if len(text) > 120 or not DATASET_NAME_RE.fullmatch(text):
        return "noisy_dataset_not_filename"
    lower = text.lower()
    if (lower in HELPER_DATASETS or lower.startswith("dec_")) and case_type not in {"value_code", "code_table"}:
        return "noisy_dataset_helper_decoder"
    return None


def source_document_reason(row: dict[str, Any]) -> str | None:
    docs = [normalize(doc) for doc in as_list(row.get("source_documents"))]
    if not docs:
        return "missing_source_document"
    term = normalize(row.get("expected_main_term"))
    if docs == [term]:
        return "source_document_is_term"
    if not any(SOURCE_DOCUMENT_RE.search(doc) for doc in docs):
        return "missing_real_source_document"
    return None


def rejection_row(row: dict[str, Any], reason: str, dataset_name: str) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "dataset": dataset_name,
        "question": row.get("question"),
        "expected_main_term": row.get("expected_main_term"),
        "rejected_reason": reason,
        "source_documents": as_list(row.get("source_documents")),
        "source_fragments": as_list(row.get("source_fragments")),
    }


def validate_label_row(row: dict[str, Any], dataset_name: str) -> list[dict[str, Any]]:
    rejected: list[dict[str, Any]] = []
    reason = term_noise_reason(row.get("expected_main_term"))
    if reason:
        rejected.append(rejection_row(row, reason, dataset_name))
    for snippet in as_list(row.get("expected_answer_contains")):
        reason = answer_noise_reason(snippet)
        if reason:
            rejected.append(rejection_row(row, reason, dataset_name))
    for dataset in as_list(row.get("expected_datasets")):
        reason = dataset_noise_reason(dataset, row.get("case_type"))
        if reason:
            rejected.append(rejection_row(row, reason, dataset_name))
    reason = source_document_reason(row)
    if reason:
        rejected.append(rejection_row(row, reason, dataset_name))
    return rejected


def load_inputs(
    gold_core_path: Path,
    pseudo_gold_path: Path,
    candidate_path: Path,
    developer_overrides_path: Path,
    developer_corrected_path: Path,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "gold_core": read_jsonl(gold_core_path),
        "pseudo_gold": read_jsonl(pseudo_gold_path),
        "pseudo_candidate": read_jsonl(candidate_path),
        "developer_overrides": read_jsonl(developer_overrides_path),
        "developer_corrected": read_jsonl(developer_corrected_path),
    }


def executable_failures(rows: list[dict[str, Any]], dataset_name: str, answer_func: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        actual = answer_func(str(row.get("question", "")))
        row_failures = evaluate_case(row, actual)
        if row_failures:
            failed = rejection_row(row, "executable_expectation_failed", dataset_name)
            failed["failures"] = row_failures
            failed["actual_main_term"] = actual.get("main_term")
            failed["actual_curated_definition_found"] = actual.get("curated_definition_found")
            failures.append(failed)
    return failures


def count_no_answer(rows_by_name: dict[str, list[dict[str, Any]]]) -> int:
    rows = [row for rows in rows_by_name.values() for row in rows]
    return sum(1 for row in rows if row.get("case_type") == "no_answer" or row.get("expected_curated_definition_found") is False)


def write_report(
    path: Path,
    rows_by_name: dict[str, list[dict[str, Any]]],
    rejected_rows: list[dict[str, Any]],
    gold_core_failures: list[dict[str, Any]],
) -> None:
    source_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for name in ("gold_core", "pseudo_gold", "pseudo_candidate", "developer_overrides", "developer_corrected"):
        for row in rows_by_name.get(name, []):
            type_counts[str(row.get("case_type") or "unknown")] += 1
            for doc in as_list(row.get("source_documents")):
                source_counts[str(doc)] += 1
    reason_counts = Counter(row.get("rejected_reason", "unknown") for row in rejected_rows)
    gold_docs = {doc for row in rows_by_name.get("gold_core", []) for doc in as_list(row.get("source_documents"))}
    candidate_docs = {doc for row in rows_by_name.get("pseudo_candidate", []) for doc in as_list(row.get("source_documents"))}
    docs_without_gold = sorted(candidate_docs - gold_docs)

    lines = [
        "# Label quality report",
        "",
        f"gold_core case count: {len(rows_by_name.get('gold_core', []))}",
        f"pseudo_gold case count: {len(rows_by_name.get('pseudo_gold', []))}",
        f"pseudo_candidate case count: {len(rows_by_name.get('pseudo_candidate', []))}",
        f"developer_corrected case count: {len(rows_by_name.get('developer_overrides', [])) + len(rows_by_name.get('developer_corrected', []))}",
        f"rejected candidate count: {len(rejected_rows)}",
        f"no-answer case count: {count_no_answer(rows_by_name)}",
        "",
        "## Counts by source document",
    ]
    lines += [f"- {doc}: {count}" for doc, count in source_counts.most_common()] or ["- None"]
    lines += ["", "## Counts by case_type"]
    lines += [f"- {case_type}: {count}" for case_type, count in type_counts.most_common()] or ["- None"]
    lines += ["", "## Rejected/warning reasons"]
    lines += [f"- {reason}: {count}" for reason, count in reason_counts.most_common()] or ["- None"]
    lines += ["", "## gold_core failures"]
    lines += [f"- {row.get('id')}: {', '.join(row.get('failures', []))}" for row in gold_core_failures] or ["- None"]
    lines += ["", "## Source documents with no gold labels yet"]
    lines += [f"- {doc}" for doc in docs_without_gold] or ["- None"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_label_quality(
    *,
    gold_core_path: Path = DEFAULT_GOLD_CORE,
    pseudo_gold_path: Path = DEFAULT_PSEUDO_GOLD,
    candidate_path: Path = DEFAULT_PSEUDO_CANDIDATE,
    developer_overrides_path: Path = DEFAULT_DEVELOPER_OVERRIDES,
    developer_corrected_path: Path = DEFAULT_DEVELOPER_CORRECTED,
    report_path: Path = DEFAULT_REPORT,
    rejected_path: Path = DEFAULT_REJECTED,
    answer_func: Callable[[str], dict[str, Any]] = answer_definition_question_json,
) -> int:
    rows_by_name = load_inputs(gold_core_path, pseudo_gold_path, candidate_path, developer_overrides_path, developer_corrected_path)
    rejected_rows: list[dict[str, Any]] = []
    for dataset_name in ("gold_core", "pseudo_gold"):
        for row in rows_by_name[dataset_name]:
            rejected_rows.extend(validate_label_row(row, dataset_name))
    for row in rows_by_name["pseudo_candidate"]:
        for warning in as_list(row.get("candidate_quality_warnings")):
            rejected_rows.append(rejection_row(row, str(warning), "pseudo_candidate"))

    gold_core_failures = executable_failures(rows_by_name["gold_core"], "gold_core", answer_func)
    pseudo_gold_failures = executable_failures(rows_by_name["pseudo_gold"], "pseudo_gold", answer_func)
    rejected_rows.extend(gold_core_failures)
    rejected_rows.extend(pseudo_gold_failures)

    write_jsonl(rejected_path, rejected_rows)
    write_report(report_path, rows_by_name, rejected_rows, gold_core_failures)
    if any(row.get("dataset") == "gold_core" for row in rejected_rows):
        print(f"Label quality audit failed; see {report_path}")
        return 1
    print(f"Label quality audit passed; see {report_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-core", type=Path, default=DEFAULT_GOLD_CORE)
    parser.add_argument("--pseudo-gold", type=Path, default=DEFAULT_PSEUDO_GOLD)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_PSEUDO_CANDIDATE)
    parser.add_argument("--developer-overrides", type=Path, default=DEFAULT_DEVELOPER_OVERRIDES)
    parser.add_argument("--developer-corrected", type=Path, default=DEFAULT_DEVELOPER_CORRECTED)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--rejected", type=Path, default=DEFAULT_REJECTED)
    args = parser.parse_args(argv)
    return audit_label_quality(
        gold_core_path=args.gold_core,
        pseudo_gold_path=args.pseudo_gold,
        candidate_path=args.candidates,
        developer_overrides_path=args.developer_overrides,
        developer_corrected_path=args.developer_corrected,
        report_path=args.report,
        rejected_path=args.rejected,
    )

if __name__ == "__main__":
    raise SystemExit(main())
