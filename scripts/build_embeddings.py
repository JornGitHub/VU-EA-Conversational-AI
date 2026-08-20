#!/usr/bin/env python3
"""Build the local semantic index from the same official documentation.

Vectors are produced by the local Ollama server (default model
``nomic-embed-text``), so this stays free, key-free and offline after the model
has been pulled once.

    python scripts/build_embeddings.py
    python scripts/build_embeddings.py --model embeddinggemma
    python scripts/build_embeddings.py --dry-run
    python scripts/build_embeddings.py --status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.definitions.semantic import build_semantic_index, semantic_status
from src.llm.embeddings import DEFAULT_BASE_URL, DEFAULT_EMBED_MODEL, EmbeddingError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_EMBED_MODEL, help=f"Ollama embedding model (default: {DEFAULT_EMBED_MODEL}).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Ollama base URL (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--batch-size", type=int, default=16, help="How many fragments to embed per request.")
    parser.add_argument("--dry-run", action="store_true", help="Only report how many fragments would be embedded.")
    parser.add_argument("--status", action="store_true", help="Print the status of the existing index and exit.")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(semantic_status(), ensure_ascii=False, indent=2))
        return 0

    try:
        report = build_semantic_index(
            model=args.model,
            base_url=args.base_url,
            batch_size=args.batch_size,
            progress=print,
            dry_run=args.dry_run,
        )
    except EmbeddingError as exc:
        print(f"Semantische index niet gebouwd: {exc}")
        print(f"Controleer of Ollama draait en of het model aanwezig is: ollama pull {args.model}")
        print("De app blijft werken met de lexicale zoeklaag.")
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
