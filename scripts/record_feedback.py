#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.evaluation_utils import normalize_question, read_jsonl, stable_id, utc_now_iso, write_jsonl

DEFAULT_OVERRIDES = ROOT / "data/evaluation/developer_feedback_overrides.jsonl"


def parse_bool(value: Any) -> bool | None:
    if value is None or value == "": return None
    if isinstance(value, bool): return value
    return str(value).strip().lower() in {"1", "true", "yes", "ja"}


def build_feedback_case(data: dict[str, Any]) -> dict[str, Any]:
    question = data.get("question", "")
    expected_contains = data.get("expected_answer_contains")
    if expected_contains is None and data.get("corrected_answer"):
        expected_contains = [data["corrected_answer"]]
    row = {
        "id": data.get("id") or stable_id("feedback", question),
        "question": question,
        "wrong_answer": data.get("wrong_answer", ""),
        "corrected_answer": data.get("corrected_answer", ""),
        "expected_main_term": data.get("expected_main_term") or None,
        "expected_answer_contains": expected_contains or [],
        "expected_curated_definition_found": parse_bool(data.get("expected_curated_definition_found")),
        "correction_reason": data.get("correction_reason") or data.get("reason", ""),
        "source_documents": data.get("source_documents", []),
        "source_fragments": data.get("source_fragments", []),
        "label_status": "developer_corrected",
        "case_type": data.get("case_type", "no_answer" if parse_bool(data.get("expected_curated_definition_found")) is False else "definition"),
        "created_by": "developer_feedback",
        "last_updated": utc_now_iso(),
    }
    return row


def upsert_feedback(row: dict[str, Any], path: Path = DEFAULT_OVERRIDES) -> list[dict[str, Any]]:
    rows = read_jsonl(path); key = normalize_question(row.get("question", "")); replaced = False
    out=[]
    for existing in rows:
        if normalize_question(existing.get("question", "")) == key:
            out.append(row); replaced = True
        else: out.append(existing)
    if not replaced: out.append(row)
    write_jsonl(path, out); return out


def record_interaction_feedback(question: str, wrong_answer: str, corrected_answer: str, reason: str, expected_main_term: str | None = None, expected_curated_definition_found: bool | None = None) -> dict[str, Any]:
    row = build_feedback_case(locals()); upsert_feedback(row); return row


def main(argv=None) -> int:
    p=argparse.ArgumentParser(); p.add_argument("--from-json", type=Path); p.add_argument("--question"); p.add_argument("--wrong-answer", default=""); p.add_argument("--corrected-answer", default=""); p.add_argument("--expected-main-term", default=None); p.add_argument("--expected-curated-definition-found", default=None); p.add_argument("--reason", default="")
    args=p.parse_args(argv)
    data = json.loads(args.from_json.read_text(encoding="utf-8")) if args.from_json else vars(args)
    row=build_feedback_case(data); upsert_feedback(row); print(f"Recorded developer feedback case {row['id']} in {DEFAULT_OVERRIDES}"); return 0
if __name__ == "__main__": raise SystemExit(main())
