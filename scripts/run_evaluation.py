#!/usr/bin/env python3
from __future__ import annotations

import argparse, sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import load_cases_with_overrides, read_jsonl, utc_now_iso, write_jsonl
from src.definitions.search import answer_deep_context_question_json, answer_definition_question_json

EVAL_DIR = ROOT / "data/evaluation"
DEFAULT_GOLD_CORE = EVAL_DIR / "gold_core_questions.jsonl"
DEFAULT_PSEUDO = EVAL_DIR / "pseudo_gold_questions.jsonl"
DEFAULT_CANDIDATES = EVAL_DIR / "pseudo_candidate_questions.jsonl"
DEFAULT_OVERRIDES = EVAL_DIR / "developer_feedback_overrides.jsonl"
DEFAULT_RESULTS = EVAL_DIR / "evaluation_results.jsonl"
DEFAULT_REPORT = EVAL_DIR / "evaluation_report.md"

DATASET_PATHS = {
    "gold_core": DEFAULT_GOLD_CORE,
    "pseudo_gold": DEFAULT_PSEUDO,
    "candidates": DEFAULT_CANDIDATES,
    "web_context": EVAL_DIR / "web_context_cases.jsonl",
}


def contains(haystack: Any, needle: str) -> bool:
    return str(needle).lower() in str(haystack).lower()


def list_contains(values: list[Any], expected: str) -> bool:
    return any(contains(v, expected) for v in values)


def evaluate_case(case: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    exp_term = case.get("expected_main_term")
    if exp_term not in (None, "") and actual.get("main_term") != exp_term:
        failures.append("expected_main_term")
    if "expected_curated_definition_found" in case and case.get("expected_curated_definition_found") is not None:
        if actual.get("curated_definition_found") is not case.get("expected_curated_definition_found"):
            failures.append("expected_curated_definition_found")
    answer = actual.get("answer", "")
    for snippet in case.get("expected_answer_contains", []) or []:
        if not contains(answer, snippet): failures.append("expected_answer_contains")
    for field in case.get("expected_fields", []) or []:
        if not list_contains(actual.get("fields", []) or [], field): failures.append("expected_fields")
    for dataset in case.get("expected_datasets", []) or []:
        if not list_contains(actual.get("datasets", []) or [], dataset): failures.append("expected_datasets")
    for snippet in case.get("forbidden_answer_contains", []) or []:
        if contains(answer, snippet): failures.append("forbidden_answer_contains")
    for field in case.get("forbidden_fields", []) or []:
        if list_contains(actual.get("fields", []) or [], field): failures.append("forbidden_fields")
    for dataset in case.get("forbidden_datasets", []) or []:
        if list_contains(actual.get("datasets", []) or [], dataset): failures.append("forbidden_datasets")
    for snippet in case.get("must_include", []) or []:
        if not contains(answer, snippet): failures.append("must_include")
    tiers = actual.get("source_tiers_used", []) or []
    for tier in case.get("source_tiers_disallowed", []) or []:
        if tier in tiers: failures.append("source_tiers_disallowed")
    answer_plus_definition = f"{actual.get('answer', '')} {actual.get('definition', '')}"
    for expected in case.get("expected_values", []) or []:
        value = str(expected.get("value", ""))
        meaning = str(expected.get("meaning_contains", ""))
        if value and not contains(answer_plus_definition, value): failures.append("expected_values")
        if meaning and not contains(answer_plus_definition, meaning): failures.append("expected_values")
    for related in case.get("expected_related_terms", []) or []:
        if not list_contains(actual.get("related_terms", []) or [], related): failures.append("expected_related_terms")
    return sorted(set(failures))


def result_row(run_id: str, case: dict[str, Any], actual: dict[str, Any], failures: list[str], timestamp: str, dataset_name: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "case_id": case.get("id"), "question": case.get("question"),
        "passed": not failures, "failures": failures, "dataset": dataset_name,
        "actual_main_term": actual.get("main_term"), "actual_answer": actual.get("answer"),
        "actual_fields": actual.get("fields", []), "actual_datasets": actual.get("datasets", []),
        "actual_curated_definition_found": actual.get("curated_definition_found"),
        "label_status": case.get("label_status"), "timestamp": timestamp,
        "case_type": case.get("case_type"), "confidence": case.get("confidence"), "needs_human_review": case.get("needs_human_review", False),
    }


def default_dataset_path() -> tuple[str, Path]:
    if DEFAULT_GOLD_CORE.exists():
        return "gold_core", DEFAULT_GOLD_CORE
    return "pseudo_gold", DEFAULT_PSEUDO


def load_dataset_cases(dataset: str, *, include_candidates: bool, overrides_path: Path) -> list[tuple[str, dict[str, Any]]]:
    dataset_names: list[str]
    if dataset == "default":
        name, path = default_dataset_path()
        dataset_names = [name]
    elif dataset == "all":
        dataset_names = ["gold_core" if DEFAULT_GOLD_CORE.exists() else "pseudo_gold", "candidates"]
    else:
        dataset_names = [dataset]
    if include_candidates and "candidates" not in dataset_names:
        dataset_names.append("candidates")

    rows: list[tuple[str, dict[str, Any]]] = []
    for name in dataset_names:
        path = DATASET_PATHS[name]
        if name == "candidates":
            cases = read_jsonl(path)
        else:
            cases = load_cases_with_overrides(path, overrides_path)
        rows.extend((name, case) for case in cases)
    return rows


def write_report(path: Path, results: list[dict[str, Any]]) -> None:
    total = len(results); failed = [r for r in results if not r["passed"]]; passed = total - len(failed)
    by_reason = Counter(f for r in failed for f in r["failures"])
    by_type = Counter(r.get("case_type") or "unknown" for r in failed)
    by_dataset = Counter(r.get("dataset") or "unknown" for r in failed)
    human_review = [r for r in failed if r.get("dataset") == "candidates" or r.get("needs_human_review")][:50]
    dev = [r for r in results if r.get("label_status") == "developer_corrected"]
    lines = ["# Evaluation report", "", f"Run timestamp: {utc_now_iso()}", "", f"Total cases: {total}", f"Passed: {passed}", f"Failed: {len(failed)}", f"Pass rate: {(passed/total*100 if total else 0):.1f}%", "", "## Failures by reason"]
    lines += [f"- {k}: {v}" for k,v in by_reason.most_common()] or ["- None"]
    lines += ["", "## Failures by case type"] + ([f"- {k}: {v}" for k,v in by_type.most_common()] or ["- None"])
    lines += ["", "## Candidate failures by dataset"] + ([f"- {k}: {v}" for k,v in by_dataset.most_common()] or ["- None"])
    lines += ["", "## Cases requiring human review"] + ([f"- {r['case_id']}: {r['question']} ({', '.join(r['failures'])})" for r in human_review] or ["- None"])
    lines += ["", "## Developer-corrected cases", f"- Total: {len(dev)}"]
    lines += ["", "## Top problematic terms"] + ([f"- {r.get('actual_main_term')}: {len(r.get('failures', []))}" for r in failed[:10]] or ["- None"])
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def run_evaluation(pseudo_path=DEFAULT_PSEUDO, overrides_path=DEFAULT_OVERRIDES, results_path=DEFAULT_RESULTS, report_path=DEFAULT_REPORT, *, case_type=None, limit=None, report_only=False, fail_on=None, dataset="default", include_candidates=False, answer_func: Callable[[str], dict[str, Any]]=answer_definition_question_json) -> int:
    if pseudo_path != DEFAULT_PSEUDO:
        DATASET_PATHS["pseudo_gold"] = Path(pseudo_path)
    rows = load_dataset_cases(dataset, include_candidates=include_candidates, overrides_path=Path(overrides_path))
    if case_type: rows = [(name, c) for name, c in rows if c.get("case_type") == case_type]
    if limit is not None: rows = rows[:limit]
    if report_only:
        write_report(Path(report_path), read_jsonl(Path(results_path))); return 0
    run_id = utc_now_iso().replace(":", ""); ts = utc_now_iso(); results=[]
    for dataset_name, case in rows:
        if dataset_name == "web_context":
            actual = answer_deep_context_question_json(str(case.get("query") or case.get("question", "")), web_mode=str(case.get("web_mode") or ("fallback" if case.get("allow_web_sources", True) else "off")), allow_external_web=bool(case.get("allow_external_web", False)))
        else:
            actual = answer_func(str(case.get("question", "")))
        failures = evaluate_case(case, actual)
        results.append(result_row(run_id, case, actual, failures, ts, dataset_name))
    write_jsonl(Path(results_path), results); write_report(Path(report_path), results)
    fail_on = set(fail_on or ["developer_corrected"])
    required_failures = [r for r in results if not r["passed"] and r.get("label_status") in fail_on and (r.get("dataset") != "candidates" or "pseudo_uncertain" in fail_on)]
    return 1 if required_failures else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fail-on", action="append", choices=["pseudo_generated", "developer_corrected", "pseudo_uncertain"], default=[])
    p.add_argument("--case-type"); p.add_argument("--limit", type=int); p.add_argument("--report-only", action="store_true")
    p.add_argument("--include-candidates", action="store_true")
    p.add_argument("--dataset", choices=["default", "gold_core", "pseudo_gold", "candidates", "web_context", "all"], default="default")
    args = p.parse_args(argv)
    fail_on = args.fail_on or ["developer_corrected"]
    code = run_evaluation(case_type=args.case_type, limit=args.limit, report_only=args.report_only, fail_on=fail_on, dataset=args.dataset, include_candidates=args.include_candidates)
    print(f"Evaluation {'failed' if code else 'completed'}; report: {DEFAULT_REPORT}")
    return code

if __name__ == "__main__": raise SystemExit(main())
