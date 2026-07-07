#!/usr/bin/env python3
from __future__ import annotations

import argparse, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import load_cases_with_overrides, normalize_question, read_jsonl, utc_now_iso, write_jsonl
from src.definitions.search import answer_definition_question_json

DEFAULT_PSEUDO = ROOT / "data/evaluation/pseudo_gold_questions.jsonl"
DEFAULT_OVERRIDES = ROOT / "data/evaluation/developer_feedback_overrides.jsonl"
DEFAULT_RESULTS = ROOT / "data/evaluation/evaluation_results.jsonl"
DEFAULT_REPORT = ROOT / "data/evaluation/evaluation_report.md"


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
    return sorted(set(failures))


def result_row(run_id: str, case: dict[str, Any], actual: dict[str, Any], failures: list[str], timestamp: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "case_id": case.get("id"), "question": case.get("question"),
        "passed": not failures, "failures": failures,
        "actual_main_term": actual.get("main_term"), "actual_answer": actual.get("answer"),
        "actual_fields": actual.get("fields", []), "actual_datasets": actual.get("datasets", []),
        "actual_curated_definition_found": actual.get("curated_definition_found"),
        "label_status": case.get("label_status"), "timestamp": timestamp,
        "case_type": case.get("case_type"), "confidence": case.get("confidence"),
    }


def write_report(path: Path, cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    total = len(results); failed = [r for r in results if not r["passed"]]; passed = total - len(failed)
    by_reason = Counter(f for r in failed for f in r["failures"])
    by_type = Counter(r.get("case_type") or "unknown" for r in failed)
    human_review = [r for r in failed if r.get("label_status") == "pseudo_generated"][:50]
    dev = [r for r in results if r.get("label_status") == "developer_corrected"]
    terms = Counter(str(next((c.get("expected_main_term") for c in cases if c.get("id") == r.get("case_id")), "")) for r in failed)
    lines = ["# Evaluation report", "", f"Run timestamp: {utc_now_iso()}", "", f"Total cases: {total}", f"Passed: {passed}", f"Failed: {len(failed)}", f"Pass rate: {(passed/total*100 if total else 0):.1f}%", "", "## Failures by reason"]
    lines += [f"- {k}: {v}" for k,v in by_reason.most_common()] or ["- None"]
    lines += ["", "## Failures by case type"] + ([f"- {k}: {v}" for k,v in by_type.most_common()] or ["- None"])
    lines += ["", "## Cases requiring human review"] + ([f"- {r['case_id']}: {r['question']} ({', '.join(r['failures'])})" for r in human_review] or ["- None"])
    lines += ["", "## Developer-corrected cases", f"- Total: {len(dev)}"]
    lines += ["", "## Top problematic terms"] + ([f"- {k}: {v}" for k,v in terms.most_common(10) if k] or ["- None"])
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def run_evaluation(pseudo_path=DEFAULT_PSEUDO, overrides_path=DEFAULT_OVERRIDES, results_path=DEFAULT_RESULTS, report_path=DEFAULT_REPORT, *, case_type=None, limit=None, report_only=False, fail_on=None, answer_func: Callable[[str], dict[str, Any]]=answer_definition_question_json) -> int:
    cases = load_cases_with_overrides(Path(pseudo_path), Path(overrides_path))
    if case_type: cases = [c for c in cases if c.get("case_type") == case_type]
    if limit is not None: cases = cases[:limit]
    if report_only:
        results = read_jsonl(Path(results_path)); write_report(Path(report_path), cases, results); return 0
    run_id = utc_now_iso().replace(":", ""); ts = utc_now_iso(); results=[]
    for case in cases:
        actual = answer_func(str(case.get("question", "")))
        failures = evaluate_case(case, actual)
        results.append(result_row(run_id, case, actual, failures, ts))
    write_jsonl(Path(results_path), results); write_report(Path(report_path), cases, results)
    fail_on = set(fail_on or ["developer_corrected"])
    required_failures = [r for r in results if not r["passed"] and r.get("label_status") in fail_on]
    return 1 if required_failures else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fail-on", action="append", choices=["pseudo_generated", "developer_corrected"], default=[])
    p.add_argument("--case-type"); p.add_argument("--limit", type=int); p.add_argument("--report-only", action="store_true")
    args = p.parse_args(argv)
    fail_on = args.fail_on or ["developer_corrected"]
    code = run_evaluation(case_type=args.case_type, limit=args.limit, report_only=args.report_only, fail_on=fail_on)
    print(f"Evaluation {'failed' if code else 'completed'}; report: {DEFAULT_REPORT}")
    return code

if __name__ == "__main__": raise SystemExit(main())
