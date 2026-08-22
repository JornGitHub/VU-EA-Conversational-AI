#!/usr/bin/env python3
"""Generate the synthetic 1cHO example dataset.

The real microdata is not in this repository and will not be until it is
cleaned for privacy. This writes a stand-in built entirely from the documented
code lists, plus a profile of the values it contains. See
``src/definitions/mock_data.py`` for what it is and is not.

    python scripts/generate_mock_data.py            # standaard 5000 rijen
    python scripts/generate_mock_data.py --rows 200 # kleiner
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.definitions.mock_data import (  # noqa: E402
    DEFAULT_ROWS,
    DEFAULT_SEED,
    SYNTHETIC_NOTICE,
    load_profile,
    write_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help=f"Aantal rijen (standaard {DEFAULT_ROWS}).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Seed (standaard {DEFAULT_SEED}); dezelfde seed geeft hetzelfde bestand.")
    args = parser.parse_args()

    csv_path, profile_path = write_dataset(rows=args.rows, seed=args.seed)
    profile = load_profile() or {}

    print(SYNTHETIC_NOTICE)
    print()
    print(f"Geschreven: {csv_path.relative_to(Path(__file__).resolve().parents[1])}")
    print(f"Geschreven: {profile_path.relative_to(Path(__file__).resolve().parents[1])}")
    print(f"Rijen: {profile.get('rows')}   Som van Aantal: {profile.get('sum_of_aantal')}")
    print(f"Velden: {len(profile.get('fields', {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
