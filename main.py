#!/usr/bin/env python3
"""One command-line entry point for installing, running, and testing the project.

Examples:
    python main.py --all
    python main.py --tests
    python main.py --dry-build
    python main.py --query "wat is een internationale student?"
    python main.py --query "waar vind ik data over internationale studenten?" --json
    python main.py --streamlit

By default this runner installs/updates packages from requirements.txt first, so a
fresh environment can run the selected checks without a separate setup step. Use
--skip-install when dependencies are already installed or when you need an
offline/fast run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
DEFAULT_QUERY = "wat is een internationale student?"


def run_command(command: list[str], description: str) -> int:
    """Run a subprocess, print a readable section header, and return its exit code."""
    print(f"\n=== {description} ===")
    print("$ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode == 0:
        print(f"✓ {description} completed")
    else:
        print(f"✗ {description} failed with exit code {completed.returncode}")
    return completed.returncode


def install_requirements() -> int:
    """Install project dependencies from requirements.txt at runner startup."""
    if not REQUIREMENTS.exists():
        print(f"requirements.txt not found at {REQUIREMENTS}")
        return 1
    return run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        "Install/update requirements",
    )


def run_unit_tests() -> int:
    """Run all unittest test modules under tests/."""
    return run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        "Unit tests",
    )


def run_dry_build() -> int:
    """Validate the knowledge-base build pipeline without overwriting artifacts."""
    return run_command(
        [sys.executable, "scripts/build_knowledge_base.py", "--dry-run"],
        "Knowledge-base dry run",
    )


def run_query(query: str, *, as_json: bool = False, llm: bool = False, model: str = "qwen3:8b") -> int:
    """Run the reusable definition search example for a single query."""
    command = [sys.executable, "zoek_definities_voorbeeld.py", query]
    if as_json:
        command.append("--json")
    if llm:
        command.extend(["--llm", "--model", model])
    return run_command(command, "Definition query")


def run_streamlit() -> int:
    """Start the Streamlit app for manual browser testing."""
    return run_command(
        [sys.executable, "-m", "streamlit", "run", "app_streamlit.py"],
        "Streamlit app",
    )


def print_test_guide() -> None:
    """Explain which files/commands are useful for different test goals."""
    guide = {
        "all_default_checks": "python main.py --all",
        "unit_tests_only": "python main.py --tests",
        "ingestion_pipeline_dry_run": "python main.py --dry-build",
        "retrieval_query_text": f'python main.py --query "{DEFAULT_QUERY}"',
        "retrieval_query_json": f'python main.py --query "{DEFAULT_QUERY}" --json',
        "streamlit_ui_manual_test": "python main.py --streamlit",
        "skip_dependency_install": "add --skip-install to any command",
    }
    print(json.dumps(guide, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install dependencies, run tests, and launch common project checks from one file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-install", action="store_true", help="Do not run pip install -r requirements.txt first.")
    parser.add_argument("--all", action="store_true", help="Run unit tests, a knowledge-base dry run, and a sample query.")
    parser.add_argument("--tests", action="store_true", help="Run all unittest tests in tests/.")
    parser.add_argument("--dry-build", action="store_true", help="Run scripts/build_knowledge_base.py --dry-run.")
    parser.add_argument("--query", help="Run one definition/retrieval query through zoek_definities_voorbeeld.py.")
    parser.add_argument("--json", action="store_true", help="Return --query output as JSON.")
    parser.add_argument("--llm", action="store_true", help="Use the local Ollama LLM layer for --query.")
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name for --llm queries.")
    parser.add_argument("--streamlit", action="store_true", help="Start app_streamlit.py for manual UI testing.")
    parser.add_argument("--guide", action="store_true", help="Print a JSON guide with common run/test commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.skip_install:
        install_status = install_requirements()
        if install_status != 0:
            return install_status

    if args.guide:
        print_test_guide()
        return 0

    statuses: list[int] = []
    if args.all:
        statuses.append(run_unit_tests())
        statuses.append(run_dry_build())
        statuses.append(run_query(DEFAULT_QUERY))
    else:
        if args.tests:
            statuses.append(run_unit_tests())
        if args.dry_build:
            statuses.append(run_dry_build())
        if args.query:
            statuses.append(run_query(args.query, as_json=args.json, llm=args.llm, model=args.model))
        if args.streamlit:
            statuses.append(run_streamlit())

    if not statuses:
        print_test_guide()
        print("\nNo run option selected; use --all for the standard full check.")
        return 0

    return 0 if all(status == 0 for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
