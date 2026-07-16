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

from src.definitions.inschrijvingen_catalog import GLOBAL_TRANSFORMATIONS, SELECTION_INFO, load_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CURATED_PATH = DATA_DIR / "ho_definities_curated.json"
INDEX_PATH = DATA_DIR / "ho_definities_index.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
FIELD_CATALOG_PATH = DATA_DIR / "inschrijvingen_aggr_2025_field_catalog.json"
PRIMARY_SOURCE_DOCUMENT = "Aggregaatbestand inschrijvingen_1cHO2025.docx"
PRIMARY_DATASET = "Inschrijvingen_aggr_UNL_2025.csv"
DEMO_QUERY = "waar vind ik internationale studenten"

CANONICAL_TERM_ALIASES = {
    "internationale studenten": "Internationale student",
    "internationale student": "Internationale student",
    "eer studenten": "EER-student",
    "eer student": "EER-student",
    "eer-studenten": "EER-student",
    "eer-student": "EER-student",
}

DATASET_EXTENSIONS = (".csv", ".asc", ".txt", ".xlsx", ".json", ".jsonl", ".pdf")
DATASET_NAME_RE = re.compile(r"\b[\w*().-]+\.(?:csv|asc|txt|xlsx|jsonl?|pdf)\b", re.I)
DECODER_DATASET_RE = re.compile(r"^(?:dec_|Dec_|DEC_)")
HELPER_DATASET_NAMES = {"hoacth.csv", "hoacth_vest.csv", "dec_nationaliteitscode.csv", "dec_landcode.csv", "dec_vopl.asc"}
OLD_YEAR_DATASET_RE = re.compile(r"^(Inschrijvingen_aggr_UNL|Diplomas_aggr_UNL|EOIcohort(?:_aggr)?_UNL|Gediplomeerdencohort(?:_aggr)?_UNL)_(?:20\d{2})(\.[^.]+)$", re.I)
CLEAN_SOURCE_LABELS = {"VH informatieproducten / 1cijferHO", "Trendrapport HO 2025"}
BAD_METADATA_PHRASES = (
    "deze indicatie",
    "nieuw deze indicatie",
    "zie bestand",
    "mogelijke waarden",
    "nationaliteit is onbekend",
    "geboorteland is onbekend",
    "1. inleiding",
    "het bestand",
    "m 31 augustus",
    "overige inschrijvingen",
)
CANONICAL_RELATED_TERMS = {
    "Student / ingeschrevene",
    "Internationale student",
    "EER-student",
    "Echte neveninschrijving",
    "Onechte neveninschrijving",
    "Instroom",
    "Uitval",
    "Studiesucces",
    "Studiewissel",
    "Switch",
    "Doorstuderen",
    "Diploma",
    "Diploma’s",
    "EOI-cohort",
    "Gediplomeerdencohort",
}

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
    "betekent",
    "definitie",
    "wordt",
    "wanneer",
    "welke",
    "welk",
    "bestand",
    "bestanden",
    "dataset",
}

MIN_SCORE_FOR_ANSWER = 14.0
NO_ANSWER_TEMPLATE = (
    'Antwoord:\n'
    'Ik heb geen betrouwbare definitie gevonden voor “{query}” in de beschikbare definitiebestanden.\n\n'
    'Mogelijk staat dit niet in de huidige HO-documentatiebronnen, of is het nog niet als definitie/veld geëxtraheerd.'
)

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




def canonical_term(term: Any) -> str:
    """Return the protected/canonical display term for known source variants."""
    raw = str(term or "").strip()
    return CANONICAL_TERM_ALIASES.get(normalize_text(raw), raw)


def canonical_aliases_for(entry: Entry) -> list[str]:
    """Return configured aliases when an entry is already the canonical term."""
    term = str(entry.get("term", ""))
    canonical = canonical_term(term)
    aliases = list(as_list(entry.get("aliases")))
    if normalize_text(term) == normalize_text(canonical):
        aliases.extend(
            alias
            for alias, target in CANONICAL_TERM_ALIASES.items()
            if normalize_text(target) == normalize_text(canonical)
        )
    return unique_preserve_order(aliases)


def canonical_preference(entry: Entry) -> int:
    """Prefer protected canonical terms over plural/source variants."""
    term = str(entry.get("term", ""))
    canonical = canonical_term(term)
    if normalize_text(term) == normalize_text(canonical) and canonical:
        return 1
    return 0

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


def _contains_bad_metadata_phrase(value: str) -> bool:
    normalized = normalize_text(value)
    return any(phrase in normalized for phrase in BAD_METADATA_PHRASES)


def sanitize_field_name(value: Any) -> str:
    field = re.sub(r"\s+", " ", str(value or "").strip())
    if not field:
        return ""
    field = re.sub(r"\s*\(NIEUW\)", "", field, flags=re.I).strip()
    field = re.split(
        r"\s+(?:Deze indicatie|Zie bestand|Mogelijke waarden|nationaliteit is onbekend|geboorteland is onbekend|1\.\s*Inleiding|Het bestand)\b",
        field,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" -–:;,.()")
    if not field or _contains_bad_metadata_phrase(field):
        return ""
    if len(field.split()) > 10 and not field.lower().startswith(("soort inschrijving", "sleutel domein")):
        return ""
    if re.search(r"\b\d+(?:\.\d+){1,}\b", field):
        return ""
    if not re.match(r"^(Indicatie|Persoonsgebonden|Inschrijvingsvorm|Soort|Sleutel|Uitval|Switch|Doorstuderen|Diploma|Instroom|Studiesucces|EOI|Gediplomeerden|Nationaliteit)\b", field, re.I):
        return ""
    return field


def sanitize_fields(fields: list[Any]) -> list[str]:
    return unique_preserve_order([clean for field in fields if (clean := sanitize_field_name(field))])



def filter_fields_for_main_term(main_term: Any, fields: list[str]) -> list[str]:
    main_tokens = set(tokenize(main_term))
    filtered: list[str] = []
    for field in fields:
        field_norm = normalize_text(field)
        if not ({"internationale", "eer"} & main_tokens) and (
            "internationale student" in field_norm or "indicatie eer" in field_norm
        ):
            continue
        filtered.append(field)
    return unique_preserve_order(filtered)

def normalize_dataset_year(name: str) -> str:
    match = OLD_YEAR_DATASET_RE.match(name)
    if match:
        return f"{match.group(1)}_2025{match.group(2)}"
    return name


def sanitize_dataset_name(value: Any, main_term: Any | None = None) -> list[str]:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return []
    if raw in CLEAN_SOURCE_LABELS:
        return [raw]
    filenames = []
    for name in DATASET_NAME_RE.findall(raw):
        normalized_name = normalize_dataset_year(name)
        if DECODER_DATASET_RE.match(normalized_name) or normalized_name.lower() in HELPER_DATASET_NAMES:
            continue
        if re.search(r"_20\d{2}\.", normalized_name) and "_2025." not in normalized_name:
            continue
        filenames.append(normalized_name)
    if filenames:
        return unique_preserve_order(filenames)
    if _contains_bad_metadata_phrase(raw):
        return []
    if raw.startswith("Trendrapport HO") or raw == "VH informatieproducten / 1cijferHO":
        return [raw]
    if len(raw.split()) > 4 or re.search(r"[.;:]", raw):
        return []
    return []


def sanitize_datasets(datasets: list[Any], main_term: Any | None = None) -> list[str]:
    clean: list[str] = []
    for dataset in datasets:
        for part in split_dataset_name(str(dataset)):
            clean.extend(sanitize_dataset_name(part, main_term))
    return unique_preserve_order(clean)


def sanitize_related_terms(terms: list[Any], curated_terms: set[str] | None = None) -> list[str]:
    allowed = {normalize_text(term): term for term in CANONICAL_RELATED_TERMS}
    if curated_terms:
        allowed.update({normalize_text(term): term for term in curated_terms})
    clean: list[str] = []
    for term in terms:
        canonical = canonical_term(str(term or "").strip())
        norm = normalize_text(canonical)
        if not norm or _contains_bad_metadata_phrase(canonical):
            continue
        if re.search(r"\b\d+(?:\.\d+){1,}\b", canonical) or "geeft aan" in canonical.lower():
            continue
        if norm in allowed:
            clean.append(allowed[norm])
    return unique_preserve_order(clean)


def preferred_metadata_entries(group: Result) -> list[Entry]:
    curated = [
        result["entry"]
        for result in group["results"]
        if result["source"] == "curated" and float(result["entry"].get("confidence", 0) or 0) >= 0.90
    ]
    return curated or [result["entry"] for result in group["results"]]


def metadata_values(group: Result, field: str) -> list[Any]:
    values: list[Any] = []
    for entry in preferred_metadata_entries(group):
        values += as_list(entry.get(field))
    return values



def is_internationalisation_term(main_term: Any) -> bool:
    tokens = set(tokenize(main_term))
    text = normalize_text(main_term)
    return bool({"internationale", "eer", "nationaliteit", "peildatum"} & tokens) or "indicatie internationale student" in text or "indicatie eer" in text


def sanitize_notes(notes: list[Any], main_term: Any) -> list[str]:
    clean: list[str] = []
    international_note_terms = ("naturalisatie", "nationaliteit", "peildatumvariant", "internationale student", "eer")
    allow_international_notes = is_internationalisation_term(main_term)
    for note in notes:
        text = re.sub(r"\s+", " ", str(note or "").strip())
        if not text:
            continue
        note_norm = normalize_text(text)
        if any(term in note_norm for term in international_note_terms) and not allow_international_notes:
            continue
        clean.append(text)
    return unique_preserve_order(clean)

def load_field_catalog_entries() -> list[Entry]:
    """Load the primary inschrijvingen field catalog as high-priority entries."""
    entries: list[Entry] = []
    for field in load_catalog():
        entries.append({
            "term": field.get("field_name"),
            "definition": field.get("description"),
            "aliases": field.get("aliases", []),
            "fields": [field.get("field_name")],
            "datasets": [field.get("dataset")],
            "source_documents": [field.get("source_document")],
            "source_document": field.get("source_document"),
            "source_path": field.get("source_path"),
            "entry_type": "primary_field_catalog",
            "field_detail": field,
            "possible_values": field.get("possible_values", []),
            "notes": field.get("notes", []),
            "references": field.get("references", []),
            "transformations": field.get("transformations", []),
        })
    return entries


def is_primary_query(query: str) -> bool:
    text = normalize_text(query)
    triggers = ["inschrijvingen", "inschrijving", "aggregaat", "unl 2025", "veld", "variabele", "kolom", "peildatum", "eer", "internationale student", "nationaliteit", "eerstejaars", "verblijfsjaar", "aantal", PRIMARY_DATASET.lower()]
    return any(normalize_text(t) in text for t in triggers) or find_catalog_field(query) is not None


def catalog_match_score(query: str, field: Entry) -> float:
    detail = field.get("field_detail", {})
    q = normalize_text(query)
    name = normalize_text(detail.get("field_name", ""))
    aliases = [normalize_text(a) for a in detail.get("aliases", [])]
    score = title_match_score(query, {"term": detail.get("field_name", ""), "aliases": detail.get("aliases", [])})
    if name and name in q:
        score += 100 + len(name.split())
    for alias in aliases:
        if alias and alias in q:
            # Broad aliases such as "internationale student" should not hijack
            # conceptual questions unless the user asks for the Indicatie field.
            if alias in {"internationale student", "international student", "eer", "eer student"} and "indicatie" not in q and PRIMARY_DATASET.lower() not in q:
                continue
            score += 20
    # Disambiguate current vs peildatum variants by requiring the qualifier when present.
    if "peildatum" in q and "peildatum" in name:
        score += 40
    if "peildatum" not in q and "peildatum" in name:
        score -= 35
    if "actueel" in q and "actueel" in name:
        score += 30
    if "actueel" in q and "peildatum" in name:
        score -= 30
    if detail.get("field_number") and re.search(rf"\bveld\s+{detail['field_number']}\b", q):
        score += 100
    return score


def find_catalog_field(query: str) -> Entry | None:
    q = normalize_text(query)
    # Only route to the field catalog when the user signals a field/column, uses
    # the dataset name, names an Indicatie field, or exactly names another field.
    field_signal = any(t in q for t in ["indicatie", "veld", "variabele", "kolom", "field", normalize_text(PRIMARY_DATASET), "aantal", "nationaliteit 1", "verblijfsjaar", "soort inschrijving"])
    catalog_entries = load_field_catalog_entries()
    exact_non_broad = any(normalize_text(e.get("field_detail", {}).get("field_name", "")) in q for e in catalog_entries)
    if not field_signal and not exact_non_broad:
        return None
    scored = [(catalog_match_score(query, e), e) for e in catalog_entries]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 12 else None


def is_all_fields_query(query: str) -> bool:
    q = normalize_text(query)
    return ("alle" in q or "layout" in q or "welke" in q) and any(w in q for w in ["velden", "variabelen", "kolommen"])


def build_field_answer(field: dict[str, Any]) -> str:
    lines = ["Antwoord:", f"{field['field_name']} is veld {field['field_number']} in {field['dataset']}.", f"Bron: {field.get('bron')}; type veld: {field.get('type_field')}.", "", "Definitie/beschrijving:", field.get("description", "")]
    if field.get("possible_values"):
        lines += ["", "Mogelijke waarden:"] + [f"- {v.get('code')} = {v.get('meaning')}" for v in field["possible_values"]]
    if field.get("notes"):
        lines += ["", "Let op / NB:"] + [f"- {n}" for n in field["notes"]]
    if field.get("transformations"):
        lines += ["", "Bewerkingen / afleidingen:"] + [f"- {t}" for t in field["transformations"]]
    if field.get("references"):
        lines += ["", "Verwijzingen:"] + [f"- {r}" for r in field["references"]]
    lines += ["", "Bronnen:", f"- {field.get('source_document')} ({field.get('source_path')})"]
    return "\n".join(lines).strip()


def build_all_fields_payload(query: str, debug: bool, source_policy: str) -> dict[str, Any]:
    catalog = load_catalog()
    fields = [{k: f.get(k) for k in ["field_number", "field_name", "bron", "type_field", "dataset", "source_document", "source_path"]} for f in catalog]
    return {
        "query": query, "intent": "all_fields", "answer": f"Antwoord:\n{PRIMARY_DATASET} bevat {len(fields)} velden uit {PRIMARY_SOURCE_DOCUMENT}.",
        "main_term": PRIMARY_DATASET, "definition": "", "fields": [f["field_name"] for f in fields], "field_table": fields, "datasets": [PRIMARY_DATASET], "notes": [], "related_terms": [], "curated_definition_found": True, "supporting_chunks": [],
        "source_policy": source_policy, "primary_source_used": True, "supplemental_sources": [], "primary_source_document": PRIMARY_SOURCE_DOCUMENT,
        "selection_info": SELECTION_INFO,
    }



def build_primary_context_payload(query: str, intent: str, debug: bool, source_policy: str) -> dict[str, Any]:
    if intent == "source_selection":
        body = [f"Het bestand {PRIMARY_DATASET} is gebaseerd op {SELECTION_INFO['based_on']}.", "Geselecteerde records:"] + [f"- {r}" for r in SELECTION_INFO["records"]]
    elif intent == "transformation":
        body = ["Voor aggregatie zijn onder meer deze bewerkingen uitgevoerd:"] + [f"- {t}" for t in GLOBAL_TRANSFORMATIONS]
    elif intent == "comparison":
        field_names = [f["field_name"] for f in load_catalog() if any(w in normalize_text(f["field_name"]) for w in ["peildatum", "actueel", "nationaliteit", "internationale"])]
        body = ["Actuele varianten gebruiken de actuele/terugwerkend bijgewerkte informatie; peildatumvarianten gebruiken de situatie op 1 oktober van het betreffende inschrijvingsjaar.", "Relevante velden:"] + [f"- {name}" for name in field_names]
    else:
        body = [f"{PRIMARY_DATASET} gebruikt {PRIMARY_SOURCE_DOCUMENT} als primaire bron."]
    return {
        "query": query, "intent": intent, "answer": "Antwoord:\n" + "\n".join(body), "main_term": PRIMARY_DATASET, "definition": "\n".join(body),
        "fields": [], "datasets": [PRIMARY_DATASET], "notes": SELECTION_INFO.get("limitations", []), "related_terms": [], "curated_definition_found": True, "supporting_chunks": [],
        "source_policy": "primary_only", "primary_source_used": True, "supplemental_sources": [], "primary_source_document": PRIMARY_SOURCE_DOCUMENT, "selection_info": SELECTION_INFO,
    }

def build_field_payload(query: str, field: Entry, intent: str, debug: bool, source_policy: str, supplemental: list[Any] | None = None) -> dict[str, Any]:
    detail = field["field_detail"]
    return {
        "query": query, "intent": intent, "answer": build_field_answer(detail), "main_term": detail.get("field_name"), "definition": detail.get("description", ""),
        "field_detail": detail, "fields": [detail.get("field_name")], "datasets": [detail.get("dataset")], "notes": detail.get("notes", []), "related_terms": detail.get("related_fields", []), "curated_definition_found": True, "supporting_chunks": [],
        "source_policy": source_policy, "primary_source_used": True, "supplemental_sources": supplemental or [], "primary_source_document": PRIMARY_SOURCE_DOCUMENT,
    }

def detect_intent(query: str) -> str:
    """Classify intents, including primary inschrijvingen field-catalog intents."""
    normalized = normalize_text(query)
    if is_all_fields_query(query):
        return "all_fields"
    if "verschil" in normalized or "vergelijk" in normalized:
        return "comparison"
    if any(p in normalized for p in ("welke records", "records geselecteerd", "waarop is het bestand gebaseerd", "selectie")):
        return "source_selection"
    if any(p in normalized for p in ("bewerking", "bewerkingen", "transformatie", "waarde 6")):
        return "transformation"
    if any(p in normalized for p in ("mogelijke waarden", "welke waarden", "wat betekent code", "waarde ")):
        return "possible_values"
    location_phrases = ("waar vind ik", "welk bestand", "welke dataset", "waar staat", "in welk bestand")
    definition_phrases = ("wat is", "wat betekent", "definitie")
    if any(phrase in normalized for phrase in location_phrases):
        return "location"
    if find_catalog_field(query) is not None and any(p in normalized for p in ("toon alles", "wat betekent", "definitie", "leg", "veld", "variabele", "kolom")):
        return "field_detail"
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
        "source_terms",
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
    candidates = [entry.get("term", ""), *canonical_aliases_for(entry)]
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
    term_tokens = set(tokenize(canonical_term(entry.get("term", ""))))

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

    return conceptual_bonus(entry, source) + (4.0 * canonical_preference(entry) if source == "curated" else 0.0) + title_score + token_score


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
            canonical_preference(result["entry"]),
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
    term = canonical_term(entry.get("term") or entry.get("field_name") or "")
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
        if result["score"] > target["best"]["score"] or (result["score"] == target["best"]["score"] and canonical_preference(result["entry"]) > canonical_preference(target["best"]["entry"])):
            target["best"] = result
        target["related_terms"].update(related_terms(entry))
        target["fields"] = unique_preserve_order(
            target["fields"]
            + as_list(entry.get("related_fields"))
            + as_list(entry.get("related_field_names"))
            + as_list(entry.get("field_name"))
            + as_list(entry.get("fields"))
        )
        target["datasets"] = split_dataset_names(
            target["datasets"]
            + as_list(entry.get("available_in_datasets"))
            + as_list(entry.get("dataset_or_file"))
            + as_list(entry.get("datasets"))
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
    if not curated_definition_found(related_group):
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


def meaningful_query_tokens(query: str) -> set[str]:
    return set(tokenize(query))

def is_reliable_match(query: str, result: Result | None) -> bool:
    if not result:
        return False
    entry = result["entry"]
    query_norm = normalize_text(query)
    term_norm = normalize_text(entry.get("term", ""))
    query_tokens = meaningful_query_tokens(query)
    term_tokens = set(tokenize(canonical_term(entry.get("term", ""))))
    if not query_tokens or not term_tokens:
        return False
    if term_norm and (term_norm in query_norm or query_norm in term_norm):
        return True
    if len(term_tokens) > 1 and term_tokens <= query_tokens:
        return True
    overlap = query_tokens & term_tokens
    coverage = len(overlap) / max(len(query_tokens), 1)
    term_coverage = len(overlap) / max(len(term_tokens), 1)
    if result["source"] == "curated" and float(entry.get("confidence", 0) or 0) >= 0.90 and "student" in query_tokens and "student" in term_tokens:
        return True
    if result["source"] == "curated" and float(entry.get("confidence", 0) or 0) >= 0.90 and coverage >= 0.67 and term_coverage >= 0.67:
        return True
    if result["score"] >= MIN_SCORE_FOR_ANSWER and coverage >= 0.75 and term_coverage >= 0.60:
        return True
    return False

def no_answer(query: str) -> str:
    return NO_ANSWER_TEMPLATE.format(query=query)

def build_answer(grouped_results: list[Result], query: str) -> str:
    """Build a concise conversational answer for the best result group."""
    if not grouped_results:
        return no_answer(query)

    intent = detect_intent(query)
    group = grouped_results[0]
    if not is_reliable_match(query, group.get("best")):
        return no_answer(query)
    best_entry = group["best"]["entry"]
    title = best_entry.get("term", "Gevonden definitie")
    definition = best_definition(group)
    fields = filter_fields_for_main_term(title, [field for field in sanitize_fields(metadata_values(group, "fields") + group["fields"]) if normalize_text(field) != normalize_text(title)])
    datasets = sanitize_datasets(metadata_values(group, "datasets") + group["datasets"], title)
    notes = sanitize_notes(notes_for_group(group), title)
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
    related_labels = sanitize_related_terms([related_term_label(other) for other in related_groups])
    if related_labels:
        lines += ["Andere mogelijke relevante begrippen:"]
        for label in related_labels:
            lines.append(f"- {label}")

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


def answer_definition_question_json(query: str, debug: bool = False, source_focus: str = "primary", include_supplemental: bool = True) -> dict[str, Any]:
    """Return structured retrieval output for LLM/chatbot grounding.

    The JSON-style dictionary separates the user query, detected intent, final
    answer text, selected definition, fields, datasets, notes and related terms.
    A future LLM should treat this payload as source material and avoid adding
    unsupported definitions from its own prior knowledge.
    """
    intent = detect_intent(query)
    primary_relevant = source_focus == "primary" and is_primary_query(query)
    source_policy = "primary_preferred" if primary_relevant else "no_difference"
    if primary_relevant and intent == "all_fields":
        return build_all_fields_payload(query, debug, "primary_only")
    if primary_relevant and intent in {"source_selection", "transformation", "comparison"}:
        return build_primary_context_payload(query, intent, debug, "primary_only")
    field = find_catalog_field(query) if primary_relevant else None
    if field is not None and intent in {"field_detail", "possible_values", "location", "definition", "general"}:
        return build_field_payload(query, field, "field_detail" if intent in {"definition", "general", "location"} else intent, debug, "primary_only")
    entries = [("primary_catalog", load_field_catalog_entries()), ("curated", load_curated_definitions()), ("index", load_index_definitions())]
    if include_supplemental:
        entries.append(("chunk", load_chunks()))
    results = search_definitions(query, entries)
    grouped_results = group_related_results(results)
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
        "source_policy": source_policy,
        "primary_source_used": any(r.get("source") == "primary_catalog" for r in results[:5]) if 'results' in locals() else False,
        "supplemental_sources": [],
        "primary_source_document": PRIMARY_SOURCE_DOCUMENT,
    }

    if grouped_results and is_reliable_match(query, grouped_results[0].get("best")):
        group = grouped_results[0]
        payload.update(
            {
                "main_term": canonical_term(group["best"]["entry"].get("term")),
                "definition": best_definition(group),
                "fields": filter_fields_for_main_term(group["best"]["entry"].get("term", ""), [
                    field
                    for field in sanitize_fields(metadata_values(group, "fields") + group["fields"])
                    if normalize_text(field) != normalize_text(group["best"]["entry"].get("term", ""))
                ]),
                "datasets": sanitize_datasets(metadata_values(group, "datasets") + group["datasets"], group["best"]["entry"].get("term", "")),
                "notes": sanitize_notes(notes_for_group(group), group["best"]["entry"].get("term", "")),
                "related_terms": sanitize_related_terms([
                    other["best"]["entry"].get("term", "Onbekend")
                    for other in related_groups_for_answer(grouped_results)
                ]),
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

