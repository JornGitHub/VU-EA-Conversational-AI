#!/usr/bin/env python3
"""One entry point for setting up, running, and testing the project.

Running this file without arguments performs the full "just work" flow:

    1. install/update everything in requirements.txt;
    2. make sure Ollama runs locally and the needed models are downloaded;
    3. build the local semantic index once, when Ollama can provide embeddings;
    4. start the Streamlit app (``python -m streamlit run app_streamlit.py``).

Examples:
    python main.py                      # install, pull models, index, start app
    python main.py --setup              # only prepare, do not start the app
    python main.py --skip-install       # start the app without touching pip
    python main.py --build-embeddings   # (re)build the semantic index
    python main.py --benchmark          # measure retrieval latency
    python main.py --tests
    python main.py --dry-build
    python main.py --query "wat is een internationale student?"
    python main.py --query "waar vind ik data over internationale studenten?" --json
    python main.py --archive-root-leftovers
    python main.py --check-hygiene

Steps that are not needed for the selected action are skipped: unit tests and
knowledge-base checks never download a model, and ``--skip-install`` /
``--skip-models`` / ``--skip-embeddings`` turn off the setup steps for fast or
offline runs.
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
    DEFAULT_EMBED_MODEL,
    DEFAULT_OLLAMA_MODEL,
    REQUIRED_OLLAMA_MODELS,
    ensure_models,
)

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
STREAMLIT_APP = "app_streamlit.py"
DEFAULT_QUERY = "wat is een internationale student?"
CORE_MODULES = ("streamlit", "requests", "docx", "pypdf", "fitz")

# A Windows console (or a redirected stdout) often uses a legacy code page that
# cannot encode check marks. Never let a status line crash the run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError, ValueError):  # pragma: no cover - stream without reconfigure
        pass


def console_supports(text: str) -> bool:
    """Return True when stdout can encode ``text`` as-is."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (LookupError, UnicodeError):
        return False
    return True


OK_MARK, FAIL_MARK = ("✓", "✗") if console_supports("✓✗") else ("[OK]", "[FAIL]")


def print_header(title: str) -> None:
    """Print a readable section header."""
    print(f"\n=== {title} ===")


def run_command(command: list[str], description: str) -> int:
    """Run a subprocess, print a readable section header, and return its exit code."""
    print_header(description)
    print("$ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode == 0:
        print(f"{OK_MARK} {description} completed")
    else:
        print(f"{FAIL_MARK} {description} failed with exit code {completed.returncode}")
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


def setup_ollama(models: list[str], base_url: str = DEFAULT_BASE_URL):
    """Ensure Ollama runs locally and the requested models are downloaded.

    Never fails the run: the retrieval layer works without Ollama, so a missing
    install only disables the optional LLM and semantic layers.
    """
    print_header("Ollama models")
    report = ensure_models(models, base_url=base_url)
    for message in report.messages:
        print(f"! {message}")
    marker = OK_MARK if report.llm_available else "!"
    print(f"{marker} {report.summary()}")
    return report


def setup_embeddings(
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_EMBED_MODEL,
    force: bool = False,
    ollama_available: bool = True,
) -> int:
    """Build the local semantic index when it is missing (or when forced).

    Runs once: after this the app answers questions that the lexical layer
    misses. Without Ollama the step is skipped with an explanation instead of
    failing, because the app works fine on lexical retrieval alone.
    """
    from src.definitions.semantic import index_exists, semantic_status
    from src.llm.embeddings import EmbeddingError

    print_header("Semantic index")
    if not ollama_available:
        print("! Overgeslagen: Ollama is niet beschikbaar, dus er kunnen geen embeddings worden gemaakt.")
        print("! De app werkt gewoon door met de lexicale zoeklaag.")
        return 0
    if index_exists() and not force:
        status = semantic_status()
        print(f"{OK_MARK} Semantische index aanwezig: {status.get('items')} vectoren ({status.get('model')})")
        if status.get("stale"):
            print("! De kennisbestanden zijn gewijzigd na de laatste build.")
            print("  Herbouw met: python main.py --build-embeddings")
        return 0

    from src.definitions.semantic import build_semantic_index

    print("Dit gebeurt eenmalig en kan enkele minuten duren.")
    try:
        build_semantic_index(model=model, base_url=base_url, progress=print)
    except EmbeddingError as exc:
        print(f"! Semantische index niet gebouwd: {exc}")
        print(f"! Zorg dat Ollama draait en het model aanwezig is: ollama pull {model}")
        print("! De app werkt gewoon door met de lexicale zoeklaag.")
        return 0
    print(f"{OK_MARK} Semantische index gereed")
    return 0


def run_benchmark(repeat: int = 3) -> int:
    """Measure retrieval latency with the web layer disabled."""
    return run_command(
        [sys.executable, "scripts/benchmark_retrieval.py", "--repeat", str(repeat)],
        "Retrieval benchmark",
    )


def run_llm_benchmark(model: str, base_url: str = DEFAULT_BASE_URL) -> int:
    """Measure how fast the local model answers on this machine."""
    return run_command(
        [sys.executable, "scripts/benchmark_llm.py", "--model", model, "--base-url", base_url],
        "LLM benchmark",
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


def ensure_mock_dataset() -> int:
    """Build the synthetic example dataset when it is missing.

    Deterministic and about a second of work, so there is no reason to make
    anyone run a second command for it. Never fatal: the app works without it.
    """
    print_header("Synthetische voorbeelddata")
    try:
        from src.definitions.mock_data import MOCK_PROFILE, write_dataset
    except Exception as error:  # noqa: BLE001 - optional step, never fatal
        print(f"Overgeslagen: {error}")
        return 0

    if MOCK_PROFILE.exists():
        print(f"{OK_MARK} Al aanwezig ({MOCK_PROFILE.name}).")
        return 0
    try:
        csv_path, _ = write_dataset()
    except Exception as error:  # noqa: BLE001
        print(f"Overgeslagen: {error}")
        return 0
    print(f"{OK_MARK} Aangemaakt: {csv_path.name} (synthetisch, geen echte studentgegevens).")
    return 0


def run_streamlit(share_on_network: bool = False) -> int:
    """Start the Streamlit app in the browser.

    With ``share_on_network`` the app also listens on the local network, so a
    phone or tablet on the same wifi can open it. The app itself still runs
    entirely on this machine.
    """
    if importlib.util.find_spec("streamlit") is None:
        print_header("Streamlit app")
        print("Streamlit is niet geïnstalleerd in deze Python-omgeving.")
        print("Draai `python main.py` zonder --skip-install, of `pip install -r requirements.txt`.")
        return 1

    command = [sys.executable, "-m", "streamlit", "run", STREAMLIT_APP]
    if share_on_network:
        command += ["--server.address", "0.0.0.0"]
        from src.pairing import local_network_address  # lokaal: src hoeft niet te bestaan voor --guide

        address = local_network_address()
        print_header("Bereikbaar op je eigen netwerk")
        if address:
            print(f"Open op je telefoon of tablet:  http://{address}:8501")
        else:
            print("Kon het netwerkadres van deze machine niet bepalen.")
        print("Streamlit toont hieronder zelf de exacte 'Network URL'; gebruik die als bovenstaande")
        print("niet werkt. Telefoon en laptop moeten op hetzelfde wifi-netwerk zitten.")
        print("Let op: iedereen op dit netwerk kan de app nu openen. Stop met Ctrl+C.")
    return run_command(command, "Streamlit app")


def print_test_guide() -> None:
    """Explain which files/commands are useful for different test goals."""
    guide = {
        "install_models_and_start_app": "python main.py",
        "setup_only": "python main.py --setup",
        "build_semantic_index": "python main.py --build-embeddings",
        "retrieval_benchmark": "python main.py --benchmark",
        "llm_speed_benchmark": "python main.py --benchmark-llm",
        "all_default_checks": "python main.py --all",
        "unit_tests_only": "python main.py --tests",
        "ingestion_pipeline_dry_run": "python main.py --dry-build",
        "retrieval_query_text": f'python main.py --query "{DEFAULT_QUERY}"',
        "retrieval_query_json": f'python main.py --query "{DEFAULT_QUERY}" --json',
        "retrieval_query_with_local_llm": f'python main.py --query "{DEFAULT_QUERY}" --llm',
        "streamlit_ui_manual_test": "python main.py --streamlit",
        "open_from_phone_on_same_wifi": "python main.py --network",
        "archive_root_leftovers": "python main.py --archive-root-leftovers",
        "project_hygiene_check": "python main.py --check-hygiene",
        "skip_dependency_install": "add --skip-install to any command",
        "skip_ollama_model_download": "add --skip-models to any command",
        "skip_semantic_index_build": "add --skip-embeddings to any command",
    }
    print(json.dumps(guide, ensure_ascii=False, indent=2))


def print_run_summary(results: list[tuple[str, int]], *, launching_app: bool) -> None:
    """Close a check run with a readable summary and the command to start the app."""
    if not results:
        return
    print_header("Samenvatting")
    for label, code in results:
        print(f"{OK_MARK if code == 0 else FAIL_MARK} {label}")
    if not launching_app:
        print("\nDit waren checks in de terminal; ze starten de app niet.")
        print("Start de VU EA Conversational AI-app met:\n  python main.py")


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
    parser.add_argument("--skip-embeddings", action="store_true", help="Do not build the local semantic index.")
    parser.add_argument("--build-embeddings", action="store_true", help="(Re)build the local semantic index and exit.")
    parser.add_argument("--benchmark", action="store_true", help="Measure retrieval latency and exit.")
    parser.add_argument("--benchmark-llm", action="store_true", help="Measure how fast the local LLM answers and exit.")
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL, help=f"Ollama embedding model (default: {DEFAULT_EMBED_MODEL}).")
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
    parser.add_argument("--network", action="store_true", help="Also serve the app on the local network, so a phone or tablet on the same wifi can open it.")
    parser.add_argument("--archive-root-leftovers", action="store_true", help="Archive generated artifacts left in the project root.")
    parser.add_argument("--check-hygiene", action="store_true", help="Warn about generated artifacts left in the project root.")
    parser.add_argument("--guide", action="store_true", help="Print a JSON guide with common run/test commands.")
    return parser.parse_args()


def selected_models(args: argparse.Namespace) -> list[str]:
    """Return the Ollama models to make available for this run.

    The chat model can be overridden with --model; the embedding model comes
    along because the semantic layer needs it.
    """
    if args.model:
        return unique([args.model, args.embed_model]) if not args.skip_embeddings else [args.model]
    if args.skip_embeddings:
        return [model for model in REQUIRED_OLLAMA_MODELS if model != args.embed_model]
    return list(REQUIRED_OLLAMA_MODELS)


def unique(values: list[str]) -> list[str]:
    """Return values without duplicates, preserving order."""
    seen: set[str] = set()
    return [value for value in values if value and not (value in seen or seen.add(value))]


def needs_ollama(args: argparse.Namespace, *, launching_app: bool) -> bool:
    """Return True when this run should have a working local LLM."""
    if args.skip_models:
        return False
    if args.setup or launching_app or args.build_embeddings or args.benchmark_llm:
        return True
    return bool(args.query) and args.llm


def needs_embeddings(args: argparse.Namespace, *, launching_app: bool) -> bool:
    """Return True when the semantic index should be built if it is missing."""
    if args.skip_embeddings or args.skip_models:
        return False
    return bool(args.setup or launching_app)


def main() -> int:
    args = parse_args()

    if args.guide:
        print_test_guide()
        return 0

    runs_checks = bool(
        args.all or args.tests or args.dry_build or args.query or args.archive_root_leftovers
        or args.check_hygiene or args.benchmark or args.benchmark_llm or args.build_embeddings
    )
    launching_app = args.streamlit or not (runs_checks or args.setup)

    if not args.skip_install:
        install_status = install_requirements()
        if install_status != 0:
            return install_status

    ollama_report = None
    if needs_ollama(args, launching_app=launching_app):
        ollama_report = setup_ollama(selected_models(args), base_url=args.ollama_url)

    ollama_available = ollama_report.server_running if ollama_report is not None else True
    if args.build_embeddings:
        setup_embeddings(base_url=args.ollama_url, model=args.embed_model, force=True, ollama_available=ollama_available)
    elif needs_embeddings(args, launching_app=launching_app):
        setup_embeddings(base_url=args.ollama_url, model=args.embed_model, ollama_available=ollama_available)

    if launching_app or args.setup:
        ensure_mock_dataset()

    if args.setup and not launching_app:
        print("\nSetup klaar. Start de app met:\n  python main.py")
        return 0

    results: list[tuple[str, int]] = []
    if args.all:
        results.append(("Unit tests", run_unit_tests()))
        results.append(("Knowledge-base dry run", run_dry_build()))
        if args.archive_root_leftovers:
            results.append(("Archive root leftovers", run_archive_root_leftovers()))
        results.append(("Voorbeeldvraag", run_query(DEFAULT_QUERY)))
    else:
        if args.tests:
            results.append(("Unit tests", run_unit_tests()))
        if args.dry_build:
            results.append(("Knowledge-base dry run", run_dry_build()))
        if args.query:
            results.append((f"Vraag: {args.query}", run_query(args.query, as_json=args.json, llm=args.llm, model=args.model or DEFAULT_OLLAMA_MODEL, web_mode=args.web_mode)))
        if args.archive_root_leftovers:
            results.append(("Archive root leftovers", run_archive_root_leftovers()))
        if args.check_hygiene:
            results.append(("Project hygiene", run_hygiene_check()))
        if args.benchmark:
            results.append(("Retrieval benchmark", run_benchmark()))
        if args.benchmark_llm:
            results.append(("LLM benchmark", run_llm_benchmark(args.model or DEFAULT_OLLAMA_MODEL, args.ollama_url)))

    print_run_summary(results, launching_app=launching_app)

    if launching_app:
        results.append(("Streamlit app", run_streamlit(share_on_network=args.network)))

    return 0 if all(code == 0 for _label, code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
