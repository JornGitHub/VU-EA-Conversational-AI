from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

NOISE_PHRASES = [
    "1. Inleiding", "Het bestand", "nationaliteit is onbekend", "geboorteland is onbekend",
    "hoacth.csv", "hoacth_vest.csv", "Inschrijvingen_aggr_UNL_2023.csv", "Mogelijke waarden",
    "Deze indicatie", "NIEUW Deze indicatie",
]


def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", str(text).lower())).strip()


def stable_id(prefix: str, *parts: Any) -> str:
    normalized = "|".join(normalize_question(str(p)) for p in parts if p is not None)
    return f"{prefix}_{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:12]}"


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set(); out: list[Any] = []
    for value in values:
        if value is None or value == "":
            continue
        key = normalize_question(str(value))
        if key and key not in seen:
            seen.add(key); out.append(value)
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_cases_with_overrides(pseudo_path: Path, overrides_path: Path) -> list[dict[str, Any]]:
    by_question: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for row in read_jsonl(pseudo_path):
        key = normalize_question(row.get("question", ""))
        if key and key not in by_question:
            ordered.append(key)
        if key:
            by_question[key] = row
    for row in read_jsonl(overrides_path):
        row["label_status"] = "developer_corrected"
        key = normalize_question(row.get("question", ""))
        if not key:
            continue
        if key not in by_question:
            ordered.append(key)
        by_question[key] = row
    return [by_question[key] for key in ordered]
