"""Zoek definities voor de hoger-onderwijs conversational-AI demo.

De scriptlogica blijft bewust dependency-free: de retrieval gebruikt alleen simpele
tekstnormalisatie, handmatige scorebonussen en heuristische groepering. Dat maakt
het bestand makkelijk te begrijpen, aan te passen en op iedere Python-installatie
uit te voeren.
"""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CURATED_PATH = BASE_DIR / "ho_definities_curated.json"
INDEX_PATH = BASE_DIR / "ho_definities_index.jsonl"
DEFAULT_QUERY = "waar vind ik internationale studenten"

STOPWORDS = {
    "als",
    "data",
    "de",
    "een",
    "en",
    "er",
    "het",
    "ik",
    "in",
    "is",
    "over",
    "te",
    "telt",
    "van",
    "waar",
    "wat",
    "wie",
    "vind",
    "voor",
}

GROUP_IGNORE_WORDS = {
    "actueel",
    "actuele",
    "indicatie",
    "nieuw",
    "oktober",
    "op",
    "peildatum",
}

Result = dict[str, Any]
Entry = dict[str, Any]


def load_curated_definitions(path: Path = CURATED_PATH) -> list[Entry]:
    """Load curated conversational definitions from JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entries", [])


def load_index_definitions(path: Path = INDEX_PATH) -> list[Entry]:
    """Load raw field/documentation definitions from JSONL."""
    entries: list[Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def normalize_text(text: Any) -> str:
    """Normalize text for matching while preserving Dutch accented letters."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", str(text).lower())).strip()


def singularize_token(token: str) -> str:
    """Very small Dutch-ish singularization helper for query/term matching."""
    if len(token) > 4 and token.endswith("en"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: Any, *, remove_stopwords: bool = True) -> list[str]:
    tokens = [singularize_token(token) for token in normalize_text(text).split()]
    if remove_stopwords:
        tokens = [token for token in tokens if token and token not in STOPWORDS]
    return tokens


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def entry_search_text(entry: Entry) -> str:
    searchable_fields = [
        "term",
        "definition",
        "aliases",
        "related_fields",
        "related_field_names",
        "available_in_datasets",
        "tags",
        "source_terms",
        "field_name",
        "dataset_or_file",
    ]
    return " ".join(str(entry.get(field, "")) for field in searchable_fields)


def conceptual_bonus(entry: Entry, source: str) -> float:
    """Prefer concept/general definitions over raw technical field entries.

    Curated records are written for conversational use. Raw JSONL records with
    entry_type=field_index are primarily field inventory rows, so they should not
    outrank a curated concept that answers the user's conceptual question.
    """
    term = str(entry.get("term", ""))
    entry_type = str(entry.get("entry_type", ""))
    score = 0.0

    if source == "curated":
        score += 5.0
        if entry.get("definition"):
            score += 2.0
        if not term.lower().startswith("indicatie"):
            score += 3.0
    elif entry_type == "field_definition":
        score += 1.5
    elif entry_type == "field_index":
        score -= 1.0

    if term.lower().startswith("indicatie"):
        score -= 2.0

    return score


def title_match_score(query: str, entry: Entry) -> float:
    """Add score when query text closely matches a term/title or alias.

    This is intentionally transparent rather than ML-based: exact normalized
    phrase matches get a large boost, token coverage gets a medium boost, and
    difflib catches near matches such as singular/plural variants.
    """
    query_norm = normalize_text(query)
    query_tokens = set(tokenize(query))
    candidates = [entry.get("term", ""), *as_list(entry.get("aliases"))]
    best = 0.0

    for candidate in candidates:
        candidate_norm = normalize_text(candidate)
        candidate_tokens = set(tokenize(candidate))
        if not candidate_norm or not candidate_tokens:
            continue

        score = 0.0
        if candidate_norm in query_norm or query_norm in candidate_norm:
            score += 10.0

        overlap = query_tokens & candidate_tokens
        coverage = len(overlap) / max(len(candidate_tokens), 1)
        score += coverage * 8.0

        ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
        if ratio >= 0.65:
            score += ratio * 4.0

        best = max(best, score)

    return best


def score_entry(query: str, entry: Entry, source: str) -> float:
    query_tokens = tokenize(query)
    haystack = normalize_text(entry_search_text(entry))
    term_tokens = set(tokenize(entry.get("term", "")))

    score = conceptual_bonus(entry, source) + title_match_score(query, entry)

    # Token scoring keeps broad search behavior intact: definitions, tags and
    # dataset names still matter, but term/title hits are weighted more heavily.
    for token in query_tokens:
        if token in haystack:
            score += 1.5 if source == "curated" else 1.0
        if token in term_tokens:
            score += 3.0 if source == "curated" else 2.0

    return score


def search_definitions(query: str, entries: list[tuple[str, list[Entry]]] | None = None, limit: int = 30) -> list[Result]:
    """Search curated and index definitions, returning ranked result dicts."""
    if entries is None:
        entries = [
            ("curated", load_curated_definitions()),
            ("index", load_index_definitions()),
        ]

    results: list[Result] = []
    for source, rows in entries:
        for entry in rows:
            score = score_entry(query, entry, source)
            if score > 0:
                results.append({"score": score, "source": source, "entry": entry})

    # Stable tie-breakers: curated first, conceptual terms before Indicatie fields,
    # then alphabetically for deterministic debug output.
    results.sort(
        key=lambda result: (
            result["score"],
            1 if result["source"] == "curated" else 0,
            0 if str(result["entry"].get("term", "")).lower().startswith("indicatie") else 1,
            str(result["entry"].get("term", "")).lower(),
        ),
        reverse=True,
    )
    return results[:limit]


def concept_key(entry: Entry) -> str:
    """Build a grouping key that collapses technical variants of one concept.

    For example, "Indicatie internationale student op peildatum 1 oktober" and
    "Internationale student" both reduce to the core tokens
    "internationale student". This is intentionally conservative: we remove a
    few common technical qualifiers, but keep the substantive words.
    """
    term = str(entry.get("term") or entry.get("field_name") or "")
    tokens = tokenize(term)
    tokens = [token for token in tokens if token not in GROUP_IGNORE_WORDS and not token.isdigit()]
    if tokens and tokens[-1] == "1":
        tokens = tokens[:-1]
    return " ".join(tokens)


def related_terms(entry: Entry) -> set[str]:
    values = [entry.get("term", ""), entry.get("field_name", "")]
    values += as_list(entry.get("related_fields"))
    values += as_list(entry.get("related_field_names"))
    values += as_list(entry.get("source_terms"))
    return {normalize_text(value) for value in values if normalize_text(value)}


def same_concept(group: Result, result: Result) -> bool:
    group_key = group["key"]
    result_key = concept_key(result["entry"])
    if group_key and result_key and group_key == result_key:
        return True

    group_tokens = set(group_key.split())
    result_tokens = set(result_key.split())
    if group_tokens and result_tokens:
        overlap = group_tokens & result_tokens
        # Require most tokens to overlap; this groups variants but avoids merging
        # broad concepts like "student" with "internationale student".
        if len(overlap) >= 2 and len(overlap) / min(len(group_tokens), len(result_tokens)) >= 0.8:
            return True

    # Do not group merely because two entries share a helper field such as
    # "Indicatie actief op peildatum"; that would incorrectly merge broad
    # concepts like student counts and inschrijvingen.
    return False


def group_related_results(results: list[Result]) -> list[Result]:
    """Group ranked rows that describe the same concept and merge metadata."""
    groups: list[Result] = []
    for result in results:
        target = next((group for group in groups if same_concept(group, result)), None)
        if target is None:
            target = {
                "key": concept_key(result["entry"]),
                "score": result["score"],
                "best": result,
                "results": [],
                "related_terms": set(),
                "fields": [],
                "datasets": [],
                "sources": [],
            }
            groups.append(target)

        entry = result["entry"]
        target["results"].append(result)
        target["score"] = max(target["score"], result["score"])
        if result["score"] > target["best"]["score"]:
            target["best"] = result
        target["related_terms"].update(related_terms(entry))
        target["fields"] = unique_preserve_order(
            target["fields"]
            + as_list(entry.get("related_fields"))
            + as_list(entry.get("related_field_names"))
            + as_list(entry.get("field_name"))
        )
        target["datasets"] = unique_preserve_order(
            target["datasets"]
            + as_list(entry.get("available_in_datasets"))
            + as_list(entry.get("dataset_or_file"))
        )
        target["sources"] = unique_preserve_order(target["sources"] + [result["source"]])

    groups.sort(key=lambda group: group["score"], reverse=True)
    return groups


def best_definition(group: Result) -> str:
    curated_definitions = [
        result["entry"].get("definition", "")
        for result in group["results"]
        if result["source"] == "curated" and result["entry"].get("definition")
    ]
    if curated_definitions:
        return str(curated_definitions[0]).strip()

    definitions = [
        result["entry"].get("definition", "")
        for result in group["results"]
        if result["entry"].get("definition")
    ]
    return str(definitions[0]).strip() if definitions else "Ik heb geen uitgeschreven definitie gevonden, maar wel relevante velden en datasets."


def notes_for_group(group: Result) -> list[str]:
    notes = [str(result["entry"].get("note", "")).strip() for result in group["results"]]
    notes = [note for note in notes if note]

    field_text = " ".join(str(field).lower() for field in group["fields"])
    definition_text = " ".join(str(result["entry"].get("definition", "")).lower() for result in group["results"])
    if "peildatum" in field_text and "naturalis" in definition_text:
        notes.append(
            "Voor analyses door de tijd heen is de peildatumvariant vaak beter, "
            "omdat latere naturalisatie oudere jaren dan niet met terugwerkende kracht verandert."
        )

    return unique_preserve_order(notes)


def build_answer(grouped_results: list[Result], query: str) -> str:
    """Build a concise conversational answer for the best result group."""
    if not grouped_results:
        return "Antwoord:\nIk heb geen passende definitie of veldbeschrijving gevonden."

    group = grouped_results[0]
    best_entry = group["best"]["entry"]
    title = best_entry.get("term", "Gevonden definitie")
    lines = ["Antwoord:", best_definition(group), ""]

    fields = [field for field in group["fields"] if normalize_text(field) != normalize_text(title)]
    if fields:
        lines += ["Relevante velden:"]
        lines += [f"- {field}" for field in fields]
        lines.append("")

    if group["datasets"]:
        lines += ["Te vinden in:"]
        lines += [f"- {dataset}" for dataset in group["datasets"]]
        lines.append("")

    notes = notes_for_group(group)
    if notes:
        lines += ["Let op:"]
        lines += [f"- {note}" for note in notes]
        lines.append("")

    if len(grouped_results) > 1:
        lines += ["Andere mogelijke matches:"]
        for other in grouped_results[1:4]:
            other_term = other["best"]["entry"].get("term", "Onbekend")
            lines.append(f"- {other_term}")

    return "\n".join(lines).rstrip()


def format_debug_results(results: list[Result]) -> str:
    lines = ["", "Debug: ranked raw matches"]
    for result in results:
        entry = result["entry"]
        lines.append(f"[{result['source']} | score={result['score']:.1f}] {entry.get('term')}")
        definition = str(entry.get("definition", "")).replace("\n", " ")
        if definition:
            lines.append(definition[:400])
        datasets = as_list(entry.get("available_in_datasets")) or as_list(entry.get("dataset_or_file"))
        fields = as_list(entry.get("related_fields")) or as_list(entry.get("related_field_names")) or as_list(entry.get("field_name"))
        lines.append(f"Datasets: {datasets}")
        lines.append(f"Fields: {fields}")
        lines.append("")
    return "\n".join(lines).rstrip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zoek in HO-definities en toon een conversational antwoord.")
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_QUERY,
        help=(
            "Vraag of zoekterm. Als je geen query meegeeft, draait het script "
            f"een voorbeeldzoekopdracht: '{DEFAULT_QUERY}'."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Toon ook ruwe, gerankte zoekmatches met scores.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = [("curated", load_curated_definitions()), ("index", load_index_definitions())]
    results = search_definitions(args.query, entries)
    grouped_results = group_related_results(results)
    print(build_answer(grouped_results, args.query))
    if args.debug:
        print(format_debug_results(results))


if __name__ == "__main__":
    main()
