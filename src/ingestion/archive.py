"""Archive and hygiene helpers for generated knowledge artifacts.

Active generated knowledge files are expected to live under ``data/``. This
module only handles known generated leftovers in the project root so source
code, tests, requirements, and source documents are never moved by cleanup.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_GENERATED_ARTIFACT_NAMES = (
    "ho_definities_curated.json",
    "ho_definities_index.jsonl",
    "ho_definities_overzicht.md",
    "chunks.jsonl",
    "document_manifest.json",
    "curated_change_log.jsonl",
    "last_build_report.md",
)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def find_root_generated_artifacts(root: Path) -> list[Path]:
    """Return known generated knowledge artifacts found directly in ``root``."""
    root = root.resolve()
    found: list[Path] = []
    for name in ROOT_GENERATED_ARTIFACT_NAMES:
        candidate = root / name
        if candidate.is_file():
            found.append(candidate)
    return found


def check_project_hygiene(root: Path) -> list[str]:
    """Warn about generated knowledge artifacts that should not be in root."""
    return [
        f"WARNING: root-level generated artifact found: {_relative(root.resolve(), path)}"
        for path in find_root_generated_artifacts(root)
    ]


def _unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}_{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def _unique_file(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def archive_root_generated_artifacts(root: Path, dry_run: bool = False) -> dict[str, Any]:
    """Move known root-level generated artifacts into ``data/archive``.

    Dry runs return the intended moves without creating directories or moving
    files. Destination file names are made unique if a collision is present.
    """
    root = root.resolve()
    artifacts = find_root_generated_artifacts(root)
    base_archive = root / "data" / "archive"
    archive_dir = _unique_dir(base_archive / f"root_leftovers_{_timestamp()}")
    result: dict[str, Any] = {
        "archive_dir": _relative(root, archive_dir),
        "moved": [],
        "skipped": [],
        "dry_run": dry_run,
    }
    if not artifacts:
        result["archive_dir"] = ""
        return result

    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=False)

    for source in artifacts:
        destination = _unique_file(archive_dir / source.name)
        move = {"from": _relative(root, source), "to": _relative(root, destination)}
        result["moved"].append(move)
        if not dry_run:
            shutil.move(str(source), str(destination))
    return result


def format_archive_summary(result: dict[str, Any]) -> str:
    """Render archive cleanup details for terminals and build reports."""
    moved = result.get("moved", [])
    skipped = result.get("skipped", [])
    lines = ["## Archive cleanup", ""]
    if not moved and not skipped:
        lines.append("No root-level generated artifacts found.")
        return "\n".join(lines)
    lines += [f"Dry run: {str(result.get('dry_run', False)).lower()}", "", "Moved root-level generated artifacts:"]
    lines += [f"- {item['from']} -> {item['to']}" for item in moved] or ["- none"]
    lines += ["", "Skipped:"]
    lines += [f"- {item}" for item in skipped] or ["- none"]
    return "\n".join(lines)
