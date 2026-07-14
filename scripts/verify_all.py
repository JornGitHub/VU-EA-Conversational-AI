#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

QUERIES = [
    "wat is een internationale student?",
    "wat zijn internationale studenten?",
    "wat is instroom?",
    "wat is studiesucces?",
    "wat is uitval?",
    "wat is een EER-student?",
    "wat is een EOI-cohort?",
    "wat is een gediplomeerdencohort?",
    "wat is een onechte neveninschrijving?",
    "wat betekent wettelijk collegegeld (laag)?",
]

NOISE = [
    "1. Inleiding",
    "Het bestand",
    "nationaliteit is onbekend",
    "geboorteland is onbekend",
    "hoacth.csv",
    "hoacth_vest.csv",
    "Inschrijvingen_aggr_UNL_2023.csv",
]
HELPER_DATASET_NOISE = ["hoacth.csv", "hoacth_vest.csv", "dec_nationaliteitscode", "dec_landcode", "dec_vopl"]
INTERNATIONAL_NOTE_TERMS = ["naturalisatie", "peildatumvariant", "internationale student"]


def run_step(title: str, cmd: list[str]) -> str:
    print(f"\n=== {title} ===", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(completed.stdout, end="")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.stdout


def assert_contains(output: str, needle: str, context: str) -> None:
    if needle not in output:
        raise SystemExit(f"Expected {needle!r} in {context}.")


def assert_not_contains(output: str, needle: str, context: str) -> None:
    if needle in output:
        raise SystemExit(f"Unexpected {needle!r} in {context}.")


def extract_json_object(stdout: str) -> dict[str, Any]:
    """Parse JSON output, tolerating incidental text before/after the object."""
    stripped = stdout.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise SystemExit("Could not parse a JSON object from --json output.")


def verify_formatted_query(query: str) -> str:
    output = run_step(f"Smoke query: {query}", [PYTHON, "zoek_definities_voorbeeld.py", query])
    for noise in NOISE:
        assert_not_contains(output, noise, query)
    return output


def run_query_json(query: str) -> dict[str, Any]:
    stdout = run_step(f"Structured smoke query: {query}", [PYTHON, "zoek_definities_voorbeeld.py", query, "--json"])
    result = extract_json_object(stdout)
    assert_no_metadata_noise(result, NOISE)
    return result


def assert_main_term(result: dict[str, Any], expected: str, context: str) -> None:
    actual = result.get("main_term")
    if actual != expected:
        raise SystemExit(f"Expected main_term {expected!r} in {context}, got {actual!r}.")


def assert_answer_contains(result: dict[str, Any], expected: str, context: str) -> None:
    answer = str(result.get("answer", ""))
    if expected.lower() not in answer.lower():
        raise SystemExit(f"Expected answer to contain {expected!r} in {context}.")


def assert_no_metadata_noise(result: dict[str, Any], forbidden_terms: list[str]) -> None:
    metadata_text = " ".join(
        str(value)
        for key in ("fields", "datasets", "related_terms", "notes")
        for value in result.get(key, [])
    )
    for term in forbidden_terms:
        if term.lower() in metadata_text.lower():
            raise SystemExit(f"Unexpected metadata noise {term!r} in JSON result for {result.get('query')!r}.")


def assert_dataset_terms_absent(result: dict[str, Any], forbidden_terms: list[str], context: str) -> None:
    datasets_text = " ".join(result.get("datasets", [])).lower()
    for term in forbidden_terms:
        if term.lower() in datasets_text:
            raise SystemExit(f"Unexpected dataset term {term!r} in {context}.")


def run_structured_assertions() -> None:
    singular = run_query_json("wat is een internationale student?")
    assert_main_term(singular, "Internationale student", "singular international-student query")
    assert_answer_contains(singular, "geen Nederlandse nationaliteit", "singular international-student query")

    plural = run_query_json("wat zijn internationale studenten?")
    assert_main_term(plural, "Internationale student", "plural international-student query")

    collegegeld = run_query_json("wat betekent wettelijk collegegeld (laag)?")
    if collegegeld.get("curated_definition_found") is not False:
        raise SystemExit("Expected wettelijk collegegeld query to have curated_definition_found=False.")
    assert_answer_contains(collegegeld, "geen betrouwbare definitie gevonden", "wettelijk collegegeld no-answer")

    instroom = run_query_json("wat is instroom?")
    notes_text = " ".join(instroom.get("notes", [])).lower()
    for term in INTERNATIONAL_NOTE_TERMS:
        if term in notes_text:
            raise SystemExit(f"Unexpected internationalisation note term {term!r} in instroom notes.")

    for query in ["wat is instroom?", "wat is een gediplomeerdencohort?"]:
        result = run_query_json(query)
        assert_dataset_terms_absent(result, HELPER_DATASET_NOISE, query)

    onecht = run_query_json("wat is een onechte neveninschrijving?")
    datasets_text = " ".join(onecht.get("datasets", []))
    assert_not_contains(datasets_text, "Inschrijvingen_aggr_UNL_2023.csv", "onechte neveninschrijving datasets")
    assert_contains(datasets_text, "Inschrijvingen_aggr_UNL_2025.csv", "onechte neveninschrijving datasets")


def main() -> int:
    run_step("Unit tests before build", [PYTHON, "-m", "unittest", "discover", "tests"])
    run_step("Full knowledge-base build", [PYTHON, "scripts/build_knowledge_base.py", "--full"])
    incremental = run_step("Incremental knowledge-base build", [PYTHON, "scripts/build_knowledge_base.py"])
    assert_contains(incremental, "Source files processed: 0", "incremental build report")
    assert_contains(incremental, "Source files skipped because unchanged: 10", "incremental build report")
    run_step("Unit tests after build", [PYTHON, "-m", "unittest", "discover", "tests"])

    evaluation_dir = ROOT / "data" / "evaluation"
    gate_paths = [evaluation_dir / "gold_core_questions.jsonl", evaluation_dir / "pseudo_gold_questions.jsonl"]
    if any(path.exists() for path in gate_paths):
        run_step("Label quality audit", [PYTHON, "scripts/audit_label_quality.py"])
        run_step("Evaluation suite", [PYTHON, "scripts/run_evaluation.py", "--dataset", "gold_core", "--fail-on", "developer_corrected"])
    else:
        print("Skipping evaluation suite: no gold_core_questions.jsonl or pseudo_gold_questions.jsonl found.")

    for query in QUERIES:
        verify_formatted_query(query)
    run_structured_assertions()

    print("\n=== All verification checks passed. ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
