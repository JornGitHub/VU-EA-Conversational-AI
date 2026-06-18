"""Dependency-free retrieval for higher-education definition questions.

This module loads curated HO concepts and raw field-index rows, ranks them with
transparent lexical heuristics, groups related technical variants, and builds
text or JSON answers. Future chatbots should import ``answer_definition_question_json``
and use the returned fields as source material instead of inventing definitions.

Example:
    from src.definitions.search import answer_definition_question_json

    retrieval_result = answer_definition_question_json(user_query)
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CURATED_PATH = DATA_DIR / "ho_definities_curated.json"
INDEX_PATH = DATA_DIR / "ho_definities_index.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
DEMO_QUERY = "waar vind ik internationale studenten"

DATASET_EXTENSIONS = (".csv", ".asc", ".txt", ".xlsx", ".json", ".jsonl", ".pdf")

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
    """Load automatically cleaned/high-confidence conversational definitions from data/.

    "Curated" is a legacy file name and does not imply manual approval.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("entries", [])


def load_index_definitions(path: Path = INDEX_PATH) -> list[Entry]:
    """Load raw field/documentation definitions from JSONL."""
    entries: list[Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries



def load_chunks(path: Path = CHUNKS_PATH) -> list[Entry]:
    """Load offline-generated chunks for optional low-priority fallback search."""
    if not path.exists():
        return []
    entries: list[Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunk = json.loads(line)
            entries.append(
                {
                    "term": chunk.get("source_document", "Documentfragment"),
                    "definition": str(chunk.get("text", ""))[:500],
                    "source_document": chunk.get("source_document"),
                    "source_path": chunk.get("source_path"),
                    "page": chunk.get("page"),
                    "chunk_id": chunk.get("chunk_id"),
                    "entry_type": "chunk",
                    "text": chunk.get("text", ""),
                }
            )
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


def looks_like_dataset_name(value: str) -> bool:
    """Return True for concrete dataset filenames or filename-like patterns."""
    value = value.strip().lower()
    return any(extension in value for extension in DATASET_EXTENSIONS)


def split_dataset_name(dataset: str) -> list[str]:
    """Split combined dataset filenames, but keep descriptive labels intact.

    Labels such as "EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv"
    contain two concrete dataset filenames and should become two bullets. Labels
    such as "VH informatieproducten / 1cijferHO" are descriptive source labels,
    so they stay as one item.
    """
    dataset = str(dataset).strip()
    if " / " not in dataset:
        return [dataset] if dataset else []

    parts = [part.strip() for part in dataset.split(" / ") if part.strip()]
    if len(parts) > 1 and all(looks_like_dataset_name(part) for part in parts):
        return parts
    return [dataset] if dataset else []


def split_dataset_names(values: list[Any]) -> list[str]:
    """Split filename-like combined dataset labels and deduplicate."""
    datasets: list[str] = []
    for value in values:
        datasets.extend(split_dataset_name(str(value)))
    return unique_preserve_order(datasets)


def detect_intent(query: str) -> str:
    """Classify the user's intent so the answer can lead with definition or location."""
    normalized = normalize_text(query)
    location_phrases = ("waar vind ik", "welk bestand", "welke dataset", "waar staat")
    definition_phrases = ("wat is", "wat betekent", "definitie")
    if any(phrase in normalized for phrase in location_phrases):
        return "location"
    if any(normalized.startswith(phrase) or phrase in normalized for phrase in definition_phrases):
        return "definition"
    return "general"


def detect_query_intent(query: str) -> str:
    """Backward-compatible alias for older callers; use detect_intent instead."""
    return detect_intent(query)


def pluralize_person_phrase(phrase: str) -> str:
    """Make person-like terms read naturally in location answers."""
    phrase = phrase.strip().lower()
    slash_parts = [part.strip() for part in phrase.split("/")]
    if len(slash_parts) > 1:
        return "/".join(pluralize_person_phrase(part) for part in slash_parts)

    words = phrase.split()
    if not words:
        return phrase

    last_word = words[-1]
    if last_word == "student" or last_word.endswith("-student"):
        words[-1] = f"{last_word}en"
    elif last_word == "ingeschrevene":
        words[-1] = "ingeschrevenen"
    return " ".join(words)


def topic_label_from_group(group: Result | None) -> str:
    """Use the best matched term as a readable topic label for location answers."""
    if not group:
        return "dit onderwerp"
    term = str(group["best"]["entry"].get("term", "")).strip()
    if not term:
        return "dit onderwerp"
    return pluralize_person_phrase(term)


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
        "text",
        "source_document",
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
            score += 6.0
    elif entry_type == "field_definition":
        score += 1.5
    elif entry_type == "field_index":
        score -= 1.0
    elif entry_type == "chunk":
        score -= 3.0

    if term.lower().startswith("indicatie"):
        score -= 5.0

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

    title_score = title_match_score(query, entry)
    token_score = 0.0

    # Token scoring keeps broad search behavior intact: definitions, tags and
    # dataset names still matter, but term/title hits are weighted more heavily.
    for token in query_tokens:
        if token in haystack:
            token_score += 1.5 if source == "curated" else 1.0
        if token in term_tokens:
            token_score += 3.0 if source == "curated" else 2.0

    # Conceptual bonuses should reorder matching rows, not make every curated
    # definition match every query. This keeps the index fallback meaningful.
    if title_score == 0 and token_score == 0:
        return 0.0

    return conceptual_bonus(entry, source) + title_score + token_score


def search_definitions(
    query: str,
    entries: list[Entry] | list[tuple[str, list[Entry]]] | None = None,
    limit: int = 30,
) -> list[Result]:
    """Search definitions and return ranked result dictionaries.

    Ranking is deliberately lexical and explainable: term/title matches receive
    the strongest weight, token overlap in definitions/tags/datasets adds
    evidence, and curated conversational definitions get a small preference over
    raw field-index rows. ``entries`` may be omitted (search both data files) or
    supplied as either a flat list of entries or ``[(source, entries), ...]``.
    """
    if entries is None:
        grouped_entries: list[tuple[str, list[Entry]]] = [
            ("curated", load_curated_definitions()),
            ("index", load_index_definitions()),
            ("chunk", load_chunks()),
        ]
    elif entries and isinstance(entries[0], tuple):
        grouped_entries = entries  # type: ignore[assignment]
    else:
        grouped_entries = [("index", entries or [])]  # type: ignore[list-item]

    results: list[Result] = []
    for source, rows in grouped_entries:
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
        target["datasets"] = split_dataset_names(
            target["datasets"]
            + as_list(entry.get("available_in_datasets"))
            + as_list(entry.get("dataset_or_file"))
        )
        target["sources"] = unique_preserve_order(target["sources"] + [result["source"]])

    groups.sort(key=lambda group: group["score"], reverse=True)
    return groups


def curated_definition_found(group: Result) -> bool:
    return any(result["source"] == "curated" and result["entry"].get("definition") for result in group["results"])


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
    if definitions:
        return str(definitions[0]).strip()
    return "Ik heb geen uitgeschreven definitie gevonden, maar wel relevante velden en datasets."


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


def short_description(entry: Entry, max_length: int = 140) -> str:
    """Return a short existing description without cutting off mid-word."""
    definition = re.sub(r"\s+", " ", str(entry.get("definition", "")).strip())
    if not definition:
        return ""

    first_sentence = re.split(r"(?<=[.!?])\s+", definition, maxsplit=1)[0].strip()
    if len(first_sentence) <= max_length:
        return first_sentence

    # Prefer a complete clause over an ugly mid-word ellipsis. If no clause fits,
    # omit the description rather than showing a broken fragment.
    for separator in ("; ", ", ", ": ", " - "):
        boundary = first_sentence.rfind(separator, 0, max_length)
        if boundary >= 40:
            return first_sentence[:boundary].rstrip(" ,;:-") + "."
    return ""


def related_term_label(group: Result) -> str:
    """Format related terms; add existing descriptions for unclear one-word titles."""
    entry = group["best"]["entry"]
    term = str(entry.get("term", "Onbekend"))
    if len(tokenize(term)) <= 1:
        description = short_description(entry)
        if description:
            return f"{term} — {description}"
    return term


def is_helpful_related_group(main_group: Result, related_group: Result) -> bool:
    """Hide weak technical side matches from the normal answer.

    Debug output still shows the raw ranking. The conversational answer should
    keep nearby concepts such as Student or EER-student, but not generic technical
    one-word fields such as Voorkomen unless they overlap strongly with the main
    concept.
    """
    entry = related_group["best"]["entry"]
    term = str(entry.get("term", ""))
    term_tokens = set(tokenize(term))
    main_tokens = set(str(main_group["key"]).split())

    if term.lower().startswith("indicatie"):
        return False
    if related_group["best"]["source"] != "curated" and entry.get("entry_type") == "field_index":
        return bool(term_tokens & main_tokens) and related_group["score"] >= main_group["score"] * 0.8
    if term_tokens & main_tokens:
        return True
    if len(term_tokens) <= 1:
        return False
    return related_group["score"] >= main_group["score"] * 0.75


def related_groups_for_answer(grouped_results: list[Result], limit: int = 3) -> list[Result]:
    if not grouped_results:
        return []
    main_group = grouped_results[0]
    related: list[Result] = []
    for group in grouped_results[1:]:
        if is_helpful_related_group(main_group, group):
            related.append(group)
        if len(related) >= limit:
            break
    return related


def build_answer(grouped_results: list[Result], query: str) -> str:
    """Build a concise conversational answer for the best result group."""
    if not grouped_results:
        return "Antwoord:\nIk heb geen passende definitie of veldbeschrijving gevonden."

    intent = detect_intent(query)
    group = grouped_results[0]
    best_entry = group["best"]["entry"]
    title = best_entry.get("term", "Gevonden definitie")
    definition = best_definition(group)
    fields = [field for field in group["fields"] if normalize_text(field) != normalize_text(title)]
    datasets = group["datasets"]
    notes = notes_for_group(group)
    has_curated_definition = curated_definition_found(group)

    lines = ["Antwoord:"]
    if not has_curated_definition:
        lines.extend(
            [
                "Ik heb geen opgeschoonde definitie gevonden, maar wel relevante documentatiefragmenten:",
                "",
            ]
        )

    if intent == "location" and datasets:
        lines.append(f"Je vindt data over {topic_label_from_group(group)} vooral in de volgende bestanden:")
        lines += [f"- {dataset}" for dataset in datasets]
        lines.extend(["", "Definitie:", definition, ""])
    else:
        lines.extend([definition, ""])

    if fields:
        lines += ["Relevante velden:"]
        lines += [f"- {field}" for field in fields]
        lines.append("")

    if intent != "location" and datasets:
        lines += ["Te vinden in:"]
        lines += [f"- {dataset}" for dataset in datasets]
        lines.append("")

    if notes:
        lines += ["Let op:"]
        lines += [f"- {note}" for note in notes]
        lines.append("")

    related_groups = related_groups_for_answer(grouped_results)
    if related_groups:
        lines += ["Andere mogelijke relevante begrippen:"]
        for other in related_groups:
            lines.append(f"- {related_term_label(other)}")

    return "\n".join(lines).rstrip()


def format_debug_results(results: list[Result]) -> str:
    lines = ["", "Debug: ranked raw matches"]
    for result in results:
        entry = result["entry"]
        lines.append(f"[{result['source']} | score={result['score']:.1f}] {entry.get('term')}")
        definition = str(entry.get("definition", "")).replace("\n", " ")
        if definition:
            lines.append(definition[:400])
        datasets = split_dataset_names(
            as_list(entry.get("available_in_datasets")) or as_list(entry.get("dataset_or_file"))
        )
        fields = (
            as_list(entry.get("related_fields"))
            or as_list(entry.get("related_field_names"))
            or as_list(entry.get("field_name"))
        )
        lines.append(f"Datasets: {datasets}")
        lines.append(f"Fields: {fields}")
        lines.append("")
    return "\n".join(lines).rstrip()


def debug_match_payload(result: Result) -> dict[str, Any]:
    entry = result["entry"]
    return {
        "source": result["source"],
        "score": round(result["score"], 1),
        "term": entry.get("term"),
        "definition": entry.get("definition", ""),
        "datasets": split_dataset_names(
            as_list(entry.get("available_in_datasets")) or as_list(entry.get("dataset_or_file"))
        ),
        "fields": (
            as_list(entry.get("related_fields"))
            or as_list(entry.get("related_field_names"))
            or as_list(entry.get("field_name"))
        ),
    }


def answer_definition_question_json(query: str, debug: bool = False) -> dict[str, Any]:
    """Return structured retrieval output for LLM/chatbot grounding.

    The JSON-style dictionary separates the user query, detected intent, final
    answer text, selected definition, fields, datasets, notes and related terms.
    A future LLM should treat this payload as source material and avoid adding
    unsupported definitions from its own prior knowledge.
    """
    entries = [("curated", load_curated_definitions()), ("index", load_index_definitions()), ("chunk", load_chunks())]
    results = search_definitions(query, entries)
    grouped_results = group_related_results(results)
    intent = detect_intent(query)
    answer = build_answer(grouped_results, query)

    payload: dict[str, Any] = {
        "query": query,
        "intent": intent,
        "answer": answer,
        "main_term": None,
        "definition": "",
        "fields": [],
        "datasets": [],
        "notes": [],
        "related_terms": [],
        "curated_definition_found": False,
        "supporting_chunks": [],
    }

    if grouped_results:
        group = grouped_results[0]
        payload.update(
            {
                "main_term": group["best"]["entry"].get("term"),
                "definition": best_definition(group),
                "fields": [
                    field
                    for field in group["fields"]
                    if normalize_text(field) != normalize_text(group["best"]["entry"].get("term", ""))
                ],
                "datasets": group["datasets"],
                "notes": notes_for_group(group),
                "related_terms": [
                    other["best"]["entry"].get("term", "Onbekend")
                    for other in related_groups_for_answer(grouped_results)
                ],
                "curated_definition_found": curated_definition_found(group),
                "supporting_chunks": [
                    {
                        "chunk_id": r["entry"].get("chunk_id"),
                        "source_document": r["entry"].get("source_document"),
                        "page": r["entry"].get("page"),
                        "text": str(r["entry"].get("text") or r["entry"].get("definition", ""))[:500],
                    }
                    for r in group["results"]
                    if r["source"] == "chunk"
                ][:3],
            }
        )

    if debug:
        payload["debug_matches"] = [debug_match_payload(result) for result in results]

    return payload


def build_response_payload(query: str, debug: bool = False) -> dict[str, Any]:
    """Backward-compatible alias for structured JSON-style retrieval output."""
    return answer_definition_question_json(query, debug=debug)


def answer_definition_question(query: str, debug: bool = False) -> str:
    """Return the final answer string for chatbot, web-app or CLI integration."""
    entries = [("curated", load_curated_definitions()), ("index", load_index_definitions()), ("chunk", load_chunks())]
    results = search_definitions(query, entries)
    grouped_results = group_related_results(results)
    answer = build_answer(grouped_results, query)
    if debug:
        return answer + format_debug_results(results)
    return answer

