#!/usr/bin/env python3
"""One entry point for setting up, running, and testing the project.

Running this file without arguments performs the full "just work" flow:

    1. install/update everything in requirements.txt;
    2. make sure Ollama runs locally and the needed model(s) are downloaded;
    3. start the Streamlit app (``python -m streamlit run app_streamlit.py``).

Examples:
    python main.py                      # install, pull models, start Streamlit
    python main.py --setup              # only install dependencies and models
    python main.py --skip-install       # start Streamlit without touching pip
    python main.py --tests
    python main.py --dry-build
    python main.py --query "wat is een internationale student?"
    python main.py --query "waar vind ik data over internationale studenten?" --json
    python main.py --archive-root-leftovers
    python main.py --check-hygiene

Steps that are not needed for the selected action are skipped: unit tests and
knowledge-base checks never download an LLM model, and ``--skip-install`` /
``--skip-models`` turn off the setup steps for fast or offline runs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from src.ingestion.archive import (
    archive_root_generated_artifacts,
    check_project_hygiene,
    format_archive_summary,
)
from src.llm.ollama_setup import (
    DEFAULT_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    REQUIRED_OLLAMA_MODELS,
    ensure_models,
)

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
STREAMLIT_APP = "app_streamlit.py"
DEFAULT_QUERY = "wat is een internationale student?"
CORE_MODULES = ("streamlit", "requests", "docx", "pypdf", "fitz")


def print_header(title: str) -> None:
    """Print a readable section header."""
    print(f"\n=== {title} ===")


def run_command(command: list[str], description: str) -> int:
    """Run a subprocess, print a readable section header, and return its exit code."""
    print_header(description)
    print("$ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode == 0:
        print(f"✓ {description} completed")
    else:
        print(f"✗ {description} failed with exit code {completed.returncode}")
    return completed.returncode


def missing_core_modules() -> list[str]:
    """Return the importable-name list of core dependencies that are missing."""
    return [name for name in CORE_MODULES if importlib.util.find_spec(name) is None]


def install_requirements() -> int:
    """Install project dependencies from requirements.txt at runner startup."""
    if not REQUIREMENTS.exists():
        print(f"requirements.txt not found at {REQUIREMENTS}")
        return 1

    status = run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        "Install/update requirements",
    )
    if status == 0:
        return 0

    missing = missing_core_modules()
    if not missing:
        print(
            "pip install is mislukt, maar alle benodigde pakketten zijn al aanwezig; "
            "de run gaat verder."
        )
        return 0

    print(
        "\nInstallatie van dependencies is mislukt. Ontbrekende pakketten: "
        + ", ".join(missing)
    )
    print("Gebruik bij voorkeur een virtual environment:")
    print("  python -m venv .venv")
    print("  source .venv/bin/activate        # Windows: .venv\\Scripts\\activate")
    print("  python main.py")
    return status


def setup_ollama(models: list[str], base_url: str = DEFAULT_BASE_URL) -> int:
    """Ensure Ollama runs locally and the requested models are downloaded.

    Returns 0 even when Ollama is unavailable: the retrieval layer works without
    it, so a missing LLM only disables the optional formulation layer.
    """
    print_header("Ollama models")
    report = ensure_models(models, base_url=base_url)
    for message in report.messages:
        print(f"! {message}")
    marker = "✓" if report.llm_available else "!"
    print(f"{marker} {report.summary()}")
    return 0


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


def run_query(query: str, *, as_json: bool = False, llm: bool = False, model: str = DEFAULT_OLLAMA_MODEL, web_mode: str = "fallback") -> int:
    """Run the reusable definition search example for a single query."""
    command = [sys.executable, "zoek_definities_voorbeeld.py", query]
    if as_json:
        command.append("--json")
    command.extend(["--web-mode", web_mode])
    if llm:
        command.extend(["--llm", "--model", model])
    return run_command(command, "Definition query")


def run_archive_root_leftovers() -> int:
    """Archive known generated artifacts left in the project root."""
    result = archive_root_generated_artifacts(ROOT)
    print(format_archive_summary(result))
    return 0


def run_hygiene_check() -> int:
    """Print warnings for root-level generated artifacts without failing."""
    warnings = check_project_hygiene(ROOT)
    print("Project hygiene check:")
    if not warnings:
        print("- OK: no root-level generated artifacts found")
    else:
        for warning in warnings:
            print(f"- {warning}")
        print("\nRun:\n  python main.py --archive-root-leftovers")
    return 0


def run_streamlit() -> int:
    """Start the Streamlit app in the browser."""
    if importlib.util.find_spec("streamlit") is None:
        print_header("Streamlit app")
        print("Streamlit is niet geïnstalleerd in deze Python-omgeving.")
        print("Draai `python main.py` zonder --skip-install, of `pip install -r requirements.txt`.")
        return 1
    return run_command(
        [sys.executable, "-m", "streamlit", "run", STREAMLIT_APP],
        "Streamlit app",
    )


def print_test_guide() -> None:
    """Explain which files/commands are useful for different test goals."""
    guide = {
        "install_models_and_start_app": "python main.py",
        "setup_only": "python main.py --setup",
        "all_default_checks": "python main.py --all",
        "unit_tests_only": "python main.py --tests",
        "ingestion_pipeline_dry_run": "python main.py --dry-build",
        "retrieval_query_text": f'python main.py --query "{DEFAULT_QUERY}"',
        "retrieval_query_json": f'python main.py --query "{DEFAULT_QUERY}" --json',
        "retrieval_query_with_local_llm": f'python main.py --query "{DEFAULT_QUERY}" --llm',
        "streamlit_ui_manual_test": "python main.py --streamlit",
        "archive_root_leftovers": "python main.py --archive-root-leftovers",
        "project_hygiene_check": "python main.py --check-hygiene",
        "skip_dependency_install": "add --skip-install to any command",
        "skip_ollama_model_download": "add --skip-models to any command",
    }
    print(json.dumps(guide, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run without arguments to install dependencies, download the Ollama model(s) "
            "and start the Streamlit app. Flags below select individual steps instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-install", action="store_true", help="Do not run pip install -r requirements.txt first.")
    parser.add_argument("--skip-models", action="store_true", help="Do not check or download Ollama models.")
    parser.add_argument("--setup", action="store_true", help="Only install dependencies and Ollama models; do not start the app.")
    parser.add_argument("--all", action="store_true", help="Run unit tests, a knowledge-base dry run, and a sample query.")
    parser.add_argument("--tests", action="store_true", help="Run all unittest tests in tests/.")
    parser.add_argument("--dry-build", action="store_true", help="Run scripts/build_knowledge_base.py --dry-run.")
    parser.add_argument("--query", help="Run one definition/retrieval query through zoek_definities_voorbeeld.py.")
    parser.add_argument("--json", action="store_true", help="Return --query output as JSON.")
    parser.add_argument("--llm", action="store_true", help="Use the local Ollama LLM layer for --query.")
    parser.add_argument("--model", default=None, help=f"Ollama model to download/use (default: {DEFAULT_OLLAMA_MODEL}).")
    parser.add_argument("--ollama-url", default=DEFAULT_BASE_URL, help=f"Base URL of the local Ollama server (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--web-mode", choices=["off", "fallback", "enhance", "force"], default="fallback", help="Free-only web context mode for --query.")
    parser.add_argument("--streamlit", action="store_true", help="Start app_streamlit.py explicitly (same as running without arguments).")
    parser.add_argument("--archive-root-leftovers", action="store_true", help="Archive generated artifacts left in the project root.")
    parser.add_argument("--check-hygiene", action="store_true", help="Warn about generated artifacts left in the project root.")
    parser.add_argument("--guide", action="store_true", help="Print a JSON guide with common run/test commands.")
    return parser.parse_args()


def selected_models(args: argparse.Namespace) -> list[str]:
    """Return the Ollama models to make available for this run."""
    if args.model:
        return [args.model]
    return list(REQUIRED_OLLAMA_MODELS)


def needs_ollama(args: argparse.Namespace, *, launching_app: bool) -> bool:
    """Return True when this run should have a working local LLM."""
    if args.skip_models:
        return False
    if args.setup or launching_app:
        return True
    return bool(args.query) and args.llm


def main() -> int:
    args = parse_args()

    if args.guide:
        print_test_guide()
        return 0

    runs_checks = bool(args.all or args.tests or args.dry_build or args.query or args.archive_root_leftovers or args.check_hygiene)
    launching_app = args.streamlit or not (runs_checks or args.setup)

    if not args.skip_install:
        install_status = install_requirements()
        if install_status != 0:
            return install_status

    if needs_ollama(args, launching_app=launching_app):
        setup_ollama(selected_models(args), base_url=args.ollama_url)

    if args.setup and not launching_app:
        print("\nSetup klaar. Start de app met:\n  python main.py")
        return 0

    statuses: list[int] = []
    if args.all:
        statuses.append(run_unit_tests())
        statuses.append(run_dry_build())
        if args.archive_root_leftovers:
            statuses.append(run_archive_root_leftovers())
        statuses.append(run_query(DEFAULT_QUERY))
    else:
        if args.tests:
            statuses.append(run_unit_tests())
        if args.dry_build:
            statuses.append(run_dry_build())
        if args.query:
            statuses.append(run_query(args.query, as_json=args.json, llm=args.llm, model=args.model or DEFAULT_OLLAMA_MODEL, web_mode=args.web_mode))
        if args.archive_root_leftovers:
            statuses.append(run_archive_root_leftovers())
        if args.check_hygiene:
            statuses.append(run_hygiene_check())

    if launching_app:
        statuses.append(run_streamlit())

    return 0 if all(status == 0 for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
