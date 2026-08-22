#!/usr/bin/env python3
"""Check a 1cHO aggregate CSV against the documented field catalog.

Point this at the synthetic file today and at the privacy-cleaned export
later; the check is the same. It reports columns the documentation does not
describe, and codes that occur in the data without a documented meaning —
the two things that silently make an answer wrong.

    python scripts/check_data_against_docs.py
    python scripts/check_data_against_docs.py path/to/export.csv --delimiter ';'

Exit code 0 when data and documentation agree, 1 when they do not.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.definitions.mock_data import MOCK_CSV, compare_with_documentation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", nargs="?", default=str(MOCK_CSV), help="CSV om te controleren (standaard de synthetische dataset).")
    parser.add_argument("--delimiter", default=";", help="Scheidingsteken (standaard ';').")
    args = parser.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        print(f"Bestand niet gevonden: {path}")
        print("Genereer de synthetische dataset met: python scripts/generate_mock_data.py")
        return 1

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=args.delimiter)
        try:
            header = next(reader)
        except StopIteration:
            print(f"{path} is leeg.")
            return 1
        report = compare_with_documentation(header, reader)

    print(f"Bestand: {path}")
    print(f"Kolommen: {report['columns']}  (gedocumenteerd: {report['documented_columns']})")

    if report["undocumented_columns"]:
        print("\nKolommen zonder documentatie:")
        for name in report["undocumented_columns"]:
            print(f"  - {name}")

    if report["undocumented_codes"]:
        print("\nWaarden in de data zonder gedocumenteerde betekenis:")
        for entry in report["undocumented_codes"]:
            print(f"  - {entry['field']}: {', '.join(entry['codes'])}")

    if report["documented_codes_not_in_data"]:
        print("\nGedocumenteerde codes die niet in de data voorkomen (informatief):")
        for entry in report["documented_codes_not_in_data"][:10]:
            print(f"  - {entry['field']}: {', '.join(entry['codes'])}")

    print()
    print("Data en documentatie komen overeen." if report["ok"] else "Er zijn verschillen tussen data en documentatie.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
