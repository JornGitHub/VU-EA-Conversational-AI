#!/usr/bin/env python3
"""Export the documentation knowledge base for the browser-only search page.

A phone cannot run the app: it is a Python server with a local language model
next to it. The *retrieval* layer, though, is a lookup over a few hundred
definitions — small enough to ship as JSON and search in the browser. That is
what this writes, and it is why `docs/zoek.html` works from GitHub Pages with
no install at all.

Only documentation goes in here: definitions, field descriptions and code
lists that already live in this public repository. No microdata, and nothing
from the synthetic dataset either.

    python scripts/build_pages_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

CURATED = PROJECT_ROOT / "data" / "ho_definities_curated.json"
CATALOG = PROJECT_ROOT / "data" / "inschrijvingen_aggr_2025_field_catalog.json"
OUTPUT = PROJECT_ROOT / "docs" / "data" / "definities.json"


# Kopjes uit de brondocumenten die de tekstextractie als term heeft opgepikt.
# "Mogelijke waarden" is de kop boven een codelijst, niet een begrip.
HEADING_TERMS = {"bronnen", "toelichting", "inleiding", "definities", "let op"}


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _answerable(name: str, text: str) -> bool:
    """Mag dit item het antwoord op een vraag zijn?

    Een deel van de documentatie is tabel of doorlopende tekst die bij het
    extraheren op de verkeerde plek is geknipt. Zulke items zijn nog steeds
    nuttig om te vinden - de brontekst klopt - maar ze als definitie
    presenteren is misleidend. Twee signalen wijzen ze aan:

    * de naam is een kopje uit het document in plaats van een begrip;
    * de tekst begint niet als een zin, dus hij is midden in een alinea of
      tabel afgeknipt ("= Inschrijving voor dezelfde opleiding").
    """
    lowered = name.strip().lower()
    if lowered in HEADING_TERMS or lowered.startswith("mogelijke waarden"):
        return False
    body = text.strip()
    return bool(body) and (body[0].isupper() or body[0].isdigit() or body[0] == "[")


def _codes(entry: dict) -> list[dict[str, str]]:
    out = []
    for value in entry.get("possible_values") or []:
        code = _clean(value.get("code"))
        meaning = _clean(value.get("meaning"))
        if code or meaning:
            out.append({"code": code, "meaning": meaning})
    return out


def build() -> dict:
    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    entries: list[dict] = []

    for item in catalog:
        entries.append(
            {
                "kind": "field",
                "name": _clean(item.get("field_name")),
                "number": item.get("field_number"),
                "text": _clean(item.get("description")),
                "type": _clean(item.get("type_field")),
                "dataset": _clean(item.get("dataset")),
                "source": _clean(item.get("source_document")),
                "codes": _codes(item),
                "notes": [_clean(note) for note in (item.get("notes") or []) if _clean(note)],
                "aliases": [_clean(alias) for alias in (item.get("aliases") or []) if _clean(alias)],
            }
        )

    for item in curated:
        entries.append(
            {
                "kind": "definition",
                "name": _clean(item.get("term")),
                "text": _clean(item.get("definition")),
                "source": _clean(item.get("note")) or "1cHO-documentatie",
                "datasets": [_clean(name) for name in (item.get("available_in_datasets") or []) if _clean(name)],
                "aliases": [_clean(alias) for alias in (item.get("aliases") or []) if _clean(alias)],
                "related": [_clean(name) for name in (item.get("related_fields") or []) if _clean(name)],
                "tags": [_clean(tag) for tag in (item.get("tags") or []) if _clean(tag)],
            }
        )

    entries = [entry for entry in entries if entry["name"] and entry["text"]]
    for entry in entries:
        # Alleen de uitzondering opschrijven; 96 keer "answerable": true is ballast
        # op een verbinding die de telefoon uit moet halen.
        if not _answerable(entry["name"], entry["text"]):
            entry["answerable"] = False
    entries.sort(key=lambda entry: (entry["kind"], entry["name"].lower()))
    return {
        "generated_from": [CURATED.name, CATALOG.name],
        "entries": entries,
        "counts": {
            "fields": sum(1 for entry in entries if entry["kind"] == "field"),
            "definitions": sum(1 for entry in entries if entry["kind"] == "definition"),
        },
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    size = OUTPUT.stat().st_size
    print(f"Geschreven: {OUTPUT.relative_to(PROJECT_ROOT)}  ({size / 1024:.0f} kB)")
    print(f"  velden      : {payload['counts']['fields']}")
    print(f"  definities  : {payload['counts']['definitions']}")
    blocked = [e["name"] for e in payload["entries"] if e.get("answerable") is False]
    print(f"  niet als antwoord bruikbaar: {len(blocked)}")
    for name in blocked:
        print(f"    - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
