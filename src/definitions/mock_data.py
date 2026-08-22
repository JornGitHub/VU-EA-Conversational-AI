"""Synthetic 1cHO example data, and the checks that will outlive it.

The real microdata is not in this repository and will not be until it is
cleaned for privacy. This module generates a stand-in that follows the
documented field catalog exactly: every coded value comes from a code list in
the documentation, so nothing here is a claim about real students.

It exists for two reasons:

1. It makes definitions concrete. "Opleidingsvorm is een code" is thinner than
   seeing 1/2/3 with counts next to it.
2. It is the fixture that proves the value-level answer path works. When the
   privacy-cleaned file arrives, only the source of the rows changes; the
   profile, the answer block and :func:`compare_with_documentation` stay.

Identifiers that have no code list in the documentation (BRIN, CROHO, ISCED)
are generated *outside* the real code space on purpose — ``ZZ01`` is not a
Dutch institution and ``90001`` is not a CROHO number — so a stray export can
never be mistaken for the real thing.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .text_utils import canonical_term, normalize_text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "data" / "inschrijvingen_aggr_2025_field_catalog.json"
MOCK_DIR = PROJECT_ROOT / "data" / "mock"
MOCK_CSV = MOCK_DIR / "inschrijvingen_aggr_MOCK_2025.csv"
MOCK_PROFILE = MOCK_DIR / "mock_profile.json"

SYNTHETIC_TIER = "synthetic_example_data"
SYNTHETIC_NOTICE = (
    "SYNTHETISCHE VOORBEELDDATA - geen echte studentgegevens. "
    "Waarden komen uit de codelijsten in de documentatie; aantallen zijn verzonnen."
)

DEFAULT_ROWS = 5000
DEFAULT_SEED = 20250101

# Placeholders voor velden zonder codelijst. Bewust buiten de echte coderuimte:
# BRIN-codes zijn cijfer+letter (21PB), CROHO's zijn 5-cijferig beginnend bij 5-7.
FAKE_INSTITUTIONS = [f"ZZ{index:02d}" for index in range(1, 14)]
FAKE_PROGRAMMES = [str(90000 + index) for index in range(1, 13)]
FAKE_ISCED = [f"Z{index:03d}" for index in range(1, 9)]
FAKE_PRIOR_EDUCATION = [f"ZV{index:02d}" for index in range(1, 7)]
YEARS = [str(year) for year in range(2021, 2026)]
AGES = list(range(17, 66))


def _load_catalog() -> list[dict[str, Any]]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _codes(field: dict[str, Any]) -> list[str]:
    """Return the enumerable codes for a field, empty when there are none.

    A "code" like ``01 t/m 12`` is a documented range, not a value; it is
    expanded so the generated column still only contains documented values.
    """
    values: list[str] = []
    for entry in field.get("possible_values") or []:
        code = str(entry.get("code") or "").strip()
        if not code:
            continue
        if " t/m " in code:
            start, _, end = code.partition(" t/m ")
            try:
                width = len(start.strip())
                values.extend(f"{number:0{width}d}" for number in range(int(start), int(end) + 1))
            except ValueError:
                continue
            continue
        values.append(code)
    return values


def value_pool(field: dict[str, Any]) -> list[str]:
    """Return the pool a column is sampled from."""
    codes = _codes(field)
    if codes:
        return codes

    name = normalize_text(field.get("field_name"))
    if "inschrijvingsjaar" in name or name.startswith("eerste jaar"):
        return YEARS
    if "instelling" in name:
        return FAKE_INSTITUTIONS
    if "iscedf" in name:
        return FAKE_ISCED
    if "vooropleiding" in name:
        return FAKE_PRIOR_EDUCATION
    if "opleiding" in name:
        return FAKE_PROGRAMMES
    if "leeftijd" in name:
        return [str(age) for age in AGES]
    if name == "aantal":
        return []  # gets its own count column
    return FAKE_PROGRAMMES


def generate_rows(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) for the synthetic aggregate file.

    Deterministic: the same seed always produces the same file, so a rebuild
    never shows up as noise in a diff and tests can assert on real numbers.
    """
    catalog = _load_catalog()
    fields = sorted(catalog, key=lambda entry: entry.get("field_number") or 0)
    header = [field["field_name"] for field in fields]
    pools = {field["field_name"]: value_pool(field) for field in fields}
    generator = random.Random(seed)

    out: list[list[str]] = []
    for _ in range(rows):
        row: list[str] = []
        for field in fields:
            name = field["field_name"]
            if normalize_text(name) == "aantal":
                # Aggregaatbestand: elke rij is een combinatie plus een telling.
                row.append(str(generator.randint(1, 250)))
                continue
            pool = pools[name]
            row.append(generator.choice(pool) if pool else "")
        out.append(row)
    return header, out


def build_profile(header: list[str], rows: Iterable[list[str]]) -> dict[str, Any]:
    """Summarise the generated file: which values occur, and how often."""
    counters: dict[str, Counter] = {name: Counter() for name in header}
    total_count = 0
    row_total = 0
    count_index = next((i for i, name in enumerate(header) if normalize_text(name) == "aantal"), None)

    for row in rows:
        row_total += 1
        if count_index is not None:
            try:
                total_count += int(row[count_index])
            except (ValueError, IndexError):
                pass
        for index, name in enumerate(header):
            counters[name][row[index]] += 1

    fields: dict[str, Any] = {}
    for name in header:
        counter = counters[name]
        fields[name] = {
            "distinct_values": len(counter),
            "top_values": [
                {"value": value, "rows": count}
                for value, count in counter.most_common(12)
            ],
        }
    return {
        "notice": SYNTHETIC_NOTICE,
        "source_tier": SYNTHETIC_TIER,
        "dataset": "Inschrijvingen_aggr_UNL_2025.csv (synthetisch)",
        "rows": row_total,
        "sum_of_aantal": total_count,
        "fields": fields,
    }


def write_dataset(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> tuple[Path, Path]:
    """Write the synthetic CSV and its profile; return both paths."""
    header, generated = generate_rows(rows=rows, seed=seed)
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    with MOCK_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(generated)
    profile = build_profile(header, generated)
    profile["seed"] = seed
    MOCK_PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MOCK_CSV, MOCK_PROFILE


@lru_cache(maxsize=4)
def _cached_profile(signature: tuple[int, int] | None) -> dict[str, Any] | None:
    if signature is None:
        return None
    return json.loads(MOCK_PROFILE.read_text(encoding="utf-8"))


def load_profile() -> dict[str, Any] | None:
    """Return the profile of the synthetic dataset, or None when not built."""
    try:
        stat = MOCK_PROFILE.stat()
    except OSError:
        return None
    return _cached_profile((int(stat.st_mtime), stat.st_size))


def profile_for_field(field_name: str) -> dict[str, Any] | None:
    """Look up one field's synthetic value profile, matching names loosely."""
    profile = load_profile()
    if not profile:
        return None
    wanted = canonical_term(field_name)
    for name, summary in profile.get("fields", {}).items():
        if canonical_term(name) == wanted:
            return summary
    return None


def example_values(field_name: str, limit: int = 6) -> list[dict[str, Any]]:
    summary = profile_for_field(field_name)
    if not summary:
        return []
    return summary.get("top_values", [])[:limit]


def compare_with_documentation(header: list[str], rows: Iterable[list[str]]) -> dict[str, Any]:
    """Report where a dataset and the documented code lists disagree.

    Against the synthetic file this passes by construction — it is generated
    from those same code lists. Its value is later, on the real export: it
    names columns the documentation does not describe, and codes that appear
    in the data without a documented meaning.
    """
    catalog = {canonical_term(field["field_name"]): field for field in _load_catalog()}
    seen: dict[str, set[str]] = {name: set() for name in header}
    for row in rows:
        for index, name in enumerate(header):
            if index < len(row):
                seen[name].add(row[index])

    undocumented_columns = [name for name in header if canonical_term(name) not in catalog]
    undocumented_codes: list[dict[str, Any]] = []
    unused_codes: list[dict[str, Any]] = []

    for name in header:
        field = catalog.get(canonical_term(name))
        if not field:
            continue
        documented = set(_codes(field))
        if not documented:
            continue  # geen codelijst: elke waarde is toegestaan
        observed = {value for value in seen[name] if value != ""}
        extra = sorted(observed - documented)
        missing = sorted(documented - observed)
        if extra:
            undocumented_codes.append({"field": name, "codes": extra[:20]})
        if missing:
            unused_codes.append({"field": name, "codes": missing[:20]})

    return {
        "columns": len(header),
        "documented_columns": len(header) - len(undocumented_columns),
        "undocumented_columns": undocumented_columns,
        "undocumented_codes": undocumented_codes,
        "documented_codes_not_in_data": unused_codes,
        "ok": not undocumented_columns and not undocumented_codes,
    }


def examples_for_fields(matched_fields: Iterable[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Return synthetic value examples for the fields an answer matched.

    Deliberately not fed to the LLM: the counts are invented, and a model that
    sees numbers tends to talk about them as if they were measurements. The UI
    renders this next to the answer, under its own label.
    """
    out: list[dict[str, Any]] = []
    for field in list(matched_fields)[:limit]:
        name = field.get("field_name")
        if not name:
            continue
        values = example_values(name)
        if values:
            out.append({"field_name": name, "values": values, "source_tier": SYNTHETIC_TIER})
    return out
