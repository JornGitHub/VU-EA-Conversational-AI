"""Bootstrap helpers for the optional local Ollama layer.

``main.py`` uses this module to make a fresh machine usable with one command:
check whether the ``ollama`` CLI exists, start the local server when it is not
running yet, and pull the models the app expects. Everything here degrades
gracefully: the retrieval layer works without Ollama, so a missing install or a
failed pull is reported as a warning instead of stopping the app.

Only the standard library is used so this module also works before
``requirements.txt`` has been installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
REQUIRED_OLLAMA_MODELS: tuple[str, ...] = (DEFAULT_OLLAMA_MODEL,)
INSTALL_URL = "https://ollama.com/download"

Printer = Callable[[str], None]


@dataclass
class OllamaSetupReport:
    """Result of one ``ensure_models`` run, used for logging and exit codes."""

    cli_installed: bool = False
    server_running: bool = False
    models_present: list[str] = field(default_factory=list)
    models_pulled: list[str] = field(default_factory=list)
    models_failed: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def llm_available(self) -> bool:
        """True when the server runs and every requested model is available."""
        return self.server_running and not self.models_failed

    def summary(self) -> str:
        """Return one readable Dutch status line for the console."""
        if not self.cli_installed:
            return "Ollama niet geïnstalleerd; de app draait zonder optionele LLM-laag."
        if not self.server_running:
            return "Ollama-server niet bereikbaar; de app draait zonder optionele LLM-laag."
        if self.models_failed:
            return "Niet alle Ollama-modellen konden worden opgehaald: " + ", ".join(self.models_failed)
        available = self.models_present + self.models_pulled
        if not available:
            return "Ollama draait; er zijn geen modellen gevraagd."
        return "Ollama klaar met model(len): " + ", ".join(available)


def is_ollama_installed() -> bool:
    """Return True when the ``ollama`` CLI is on PATH."""
    return shutil.which("ollama") is not None


def _api_get(path: str, base_url: str, timeout: float) -> dict:
    url = base_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed localhost URL.
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def is_server_running(base_url: str = DEFAULT_BASE_URL, timeout: float = 2.0) -> bool:
    """Return True when the local Ollama API answers on ``/api/tags``."""
    try:
        _api_get("/api/tags", base_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return True


def list_installed_models(base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0) -> list[str]:
    """Return the model names Ollama currently has locally."""
    try:
        payload = _api_get("/api/tags", base_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    names: list[str] = []
    for entry in payload.get("models") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def model_is_installed(model: str, installed_models: Iterable[str]) -> bool:
    """Return True when ``model`` matches one of the locally installed models.

    A request without an explicit tag (``qwen3``) matches ``qwen3:latest``, which
    is how Ollama itself resolves untagged names.
    """
    wanted = model.strip()
    if not wanted:
        return False
    candidates = {wanted}
    if ":" not in wanted:
        candidates.add(f"{wanted}:latest")
    return any(name in candidates for name in installed_models)


def start_server(
    base_url: str = DEFAULT_BASE_URL,
    wait_seconds: float = 30.0,
    poll_seconds: float = 1.0,
    printer: Printer = print,
) -> bool:
    """Start ``ollama serve`` in the background and wait until the API answers.

    The server is detached from this process so it keeps running (and stays
    usable) after Streamlit is stopped with Ctrl+C.
    """
    if is_server_running(base_url):
        return True
    if not is_ollama_installed():
        return False

    printer("Ollama-server starten in de achtergrond (`ollama serve`)...")
    popen_kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    try:
        subprocess.Popen(["ollama", "serve"], **popen_kwargs)  # noqa: S603,S607 - fixed local command.
    except OSError as exc:
        printer(f"Kon `ollama serve` niet starten: {exc}")
        return False

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_server_running(base_url):
            return True
        time.sleep(poll_seconds)
    return is_server_running(base_url)


def pull_model(model: str, printer: Printer = print) -> bool:
    """Download one model with ``ollama pull`` and stream progress to stdout."""
    printer(f"Model ophalen: {model} (dit kan bij de eerste keer enkele GB's downloaden)...")
    try:
        completed = subprocess.run(["ollama", "pull", model], check=False)  # noqa: S603,S607 - fixed local command.
    except OSError as exc:
        printer(f"Kon `ollama pull {model}` niet uitvoeren: {exc}")
        return False
    if completed.returncode != 0:
        printer(f"`ollama pull {model}` is mislukt met exitcode {completed.returncode}.")
        return False
    printer(f"Model beschikbaar: {model}")
    return True


def install_hint() -> str:
    """Return a platform-aware install instruction for the Ollama CLI."""
    if sys.platform == "darwin":
        return f"Installeer Ollama via {INSTALL_URL} of met `brew install ollama`."
    if os.name == "nt":
        return f"Installeer Ollama via {INSTALL_URL} (Windows-installer) en start daarna dit script opnieuw."
    return f"Installeer Ollama via {INSTALL_URL} of met `curl -fsSL https://ollama.com/install.sh | sh`."


def ensure_models(
    models: Sequence[str] = REQUIRED_OLLAMA_MODELS,
    base_url: str = DEFAULT_BASE_URL,
    *,
    autostart_server: bool = True,
    printer: Printer = print,
) -> OllamaSetupReport:
    """Make sure Ollama runs locally and every requested model is downloaded.

    Never raises: problems are collected in the returned report so callers can
    keep going with the local-documentation-only mode.
    """
    report = OllamaSetupReport()
    wanted = [model.strip() for model in models if model and model.strip()]

    report.cli_installed = is_ollama_installed()
    if not report.cli_installed:
        report.messages.append("Ollama is niet gevonden op PATH.")
        report.messages.append(install_hint())
        report.messages.append("De app werkt zonder Ollama; alleen de optionele LLM-laag is dan uitgeschakeld.")
        return report

    report.server_running = is_server_running(base_url)
    if not report.server_running and autostart_server:
        report.server_running = start_server(base_url, printer=printer)
    if not report.server_running:
        report.messages.append(f"Ollama-server niet bereikbaar op {base_url}.")
        report.messages.append("Start de server handmatig met `ollama serve` en probeer opnieuw.")
        return report

    installed = list_installed_models(base_url)
    for model in wanted:
        if model_is_installed(model, installed):
            report.models_present.append(model)
            printer(f"Model al aanwezig: {model}")
            continue
        if pull_model(model, printer=printer):
            report.models_pulled.append(model)
            installed = list_installed_models(base_url)
        else:
            report.models_failed.append(model)
            report.messages.append(f"Model {model} kon niet worden opgehaald; de LLM-laag blijft voor dit model uit.")
    return report
