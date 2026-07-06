#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
INTERNATIONAL_NOTE = "Voor analyses door de tijd heen is de peildatumvariant vaak beter"


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


def verify_query(query: str) -> str:
    output = run_step(f"Smoke query: {query}", [PYTHON, "zoek_definities_voorbeeld.py", query])
    for noise in NOISE:
        assert_not_contains(output, noise, query)
    return output


def main() -> int:
    run_step("Unit tests before build", [PYTHON, "-m", "unittest", "discover", "tests"])
    run_step("Full knowledge-base build", [PYTHON, "scripts/build_knowledge_base.py", "--full"])
    incremental = run_step("Incremental knowledge-base build", [PYTHON, "scripts/build_knowledge_base.py"])
    assert_contains(incremental, "Source files processed: 0", "incremental build report")
    assert_contains(incremental, "Source files skipped because unchanged: 10", "incremental build report")
    run_step("Unit tests after build", [PYTHON, "-m", "unittest", "discover", "tests"])

    outputs = {query: verify_query(query) for query in QUERIES}

    assert_contains(outputs["wat betekent wettelijk collegegeld (laag)?"].lower(), "geen betrouwbare definitie gevonden", "wettelijk collegegeld no-answer")
    assert_not_contains(outputs["wat is instroom?"], INTERNATIONAL_NOTE, "instroom answer")
    assert_contains(outputs["wat is een internationale student?"], "Internationale student", "singular international-student answer")
    assert_contains(outputs["wat zijn internationale studenten?"], "Internationale student", "plural international-student answer")

    print("\n=== Verification completed successfully ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
