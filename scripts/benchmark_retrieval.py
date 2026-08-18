#!/usr/bin/env python3
"""Measure local retrieval latency, with the web layer disabled.

The knowledge files are read once per process and every entry's scoring features
are precomputed, so the first question pays a small warm-up cost and later
questions are much cheaper. This script reports both.

    python scripts/benchmark_retrieval.py
    python scripts/benchmark_retrieval.py --repeat 5 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.definitions.corpus import clear_cache, corpus_stats
from src.definitions.search import (
    answer_deep_context_question_json,
    answer_definition_question_json,
    search_definitions,
)

QUERIES = [
    "wat is een internationale student?",
    "waar vind ik data over internationale studenten?",
    "wat is instroom?",
    "wat is studiesucces?",
    "wat is uitval?",
    "wat is een EER-student?",
    "wat is een EOI-cohort?",
    "wat is een onechte neveninschrijving?",
    "welke waarden heeft Indicatie actief op peildatum?",
    "wat betekent Opleiding actueel equivalent?",
]


def timed(callable_, *args, **kwargs) -> float:
    start = time.perf_counter()
    callable_(*args, **kwargs)
    return time.perf_counter() - start


def summarize(durations: list[float]) -> dict[str, float]:
    ordered = sorted(durations)
    return {
        "runs": len(durations),
        "mean_ms": round(statistics.fmean(durations) * 1000, 2),
        "p50_ms": round(statistics.median(durations) * 1000, 2),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 2),
        "max_ms": round(max(durations) * 1000, 2),
    }


def run(repeat: int) -> dict[str, object]:
    clear_cache()
    cold = timed(answer_definition_question_json, QUERIES[0], web_mode="off")

    ranking: list[float] = []
    definition: list[float] = []
    deep: list[float] = []
    for _ in range(repeat):
        for query in QUERIES:
            ranking.append(timed(search_definitions, query))
            definition.append(timed(answer_definition_question_json, query, web_mode="off"))
            deep.append(timed(answer_deep_context_question_json, query, web_mode="off"))

    return {
        "corpus": corpus_stats(),
        "cold_start_ms": round(cold * 1000, 2),
        "ranking": summarize(ranking),
        "definition_answer": summarize(definition),
        "deep_context_answer": summarize(deep),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=3, help="How often to run the query set (default 3).")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a readable table.")
    args = parser.parse_args(argv)

    report = run(max(1, args.repeat))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    corpus = report["corpus"]
    print("Retrieval benchmark (web layer off)")
    print(f"  corpus            : {corpus} entries")
    print(f"  cold start        : {report['cold_start_ms']} ms (first question, loads and prepares the corpus)")
    for label, key in (("ranking only", "ranking"), ("definition answer", "definition_answer"), ("deep-context answer", "deep_context_answer")):
        stats = report[key]
        print(f"  {label:18}: p50 {stats['p50_ms']} ms | mean {stats['mean_ms']} ms | p95 {stats['p95_ms']} ms | max {stats['max_ms']} ms over {stats['runs']} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
