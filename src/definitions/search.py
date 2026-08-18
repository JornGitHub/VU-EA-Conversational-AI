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
from src.definitions.context_pack import build_context_pack
from src.definitions.web_sources import SOURCE_TIERS, WEB_MODE_DEFAULT, WEB_MODES, build_web_context, build_web_context_with_candidates

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


def catalog_fields() -> list[dict[str, Any]]:
    return load_catalog()


def field_term_score(query: str, field: dict[str, Any]) -> float:
    q = normalize_text(query)
    name = normalize_text(field.get("field_name", ""))
    aliases = [normalize_text(a) for a in field.get("aliases", [])]
    score = 0.0
    if name and name in q:
        score += 100 + len(name.split())
    name_tokens = set(tokenize(name))
    query_tokens = set(tokenize(q))
    if name_tokens:
        score += 20 * (len(name_tokens & query_tokens) / len(name_tokens))
    for alias in aliases:
        alias_tokens = set(tokenize(alias))
        if alias and alias in q:
            score += 35
        elif alias_tokens and alias_tokens <= query_tokens:
            score += 25
    if "actueel" in q and "actueel" in name:
        score += 20
    if "historisch" in q and "historisch" in name:
        score += 20
    if "peildatum" in q and "peildatum" in name:
        score += 30
    if "peildatum" not in q and "peildatum" in name:
        score -= 20
    return score


def match_catalog_fields(query: str, limit: int = 4, min_score: float = 18.0) -> list[dict[str, Any]]:
    scored = [(field_term_score(query, field), field) for field in catalog_fields()]
    scored.sort(key=lambda item: (item[0], len(str(item[1].get("field_name", "")))), reverse=True)
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, field in scored:
        if score < min_score:
            continue
        key = str(field.get("field_name"))
        if key not in seen:
            matches.append(field)
            seen.add(key)
        if len(matches) >= limit:
            break
    return matches



def web_mode_label(web_mode: str) -> str:
    return {
        "off": "uit",
        "fallback": "alleen bij ontbrekende lokale context",
        "enhance": "altijd proberen als extra context",
        "force": "forceer webcontext",
    }.get(web_mode, web_mode)


def web_decision_label(reason: str, attempted: bool, used: bool) -> str:
    if reason == "web_disabled":
        return "Web uitgeschakeld."
    if reason == "local_context_sufficient":
        return "Web niet geprobeerd, omdat lokale documentatie voldoende context gaf."
    if used:
        return "Bruikbare officiële webbron gevonden."
    if attempted and reason == "no_relevant_official_web_context_found":
        return "Geen bruikbare officiële webbron gevonden."
    if attempted and reason == "no_free_official_web_context_found":
        return "Geen gratis officiële webbron gevonden/gebruikt."
    if attempted and reason == "web_fetch_failed":
        return "Web geprobeerd, maar ophalen van gratis webcontext is mislukt."
    if attempted:
        return "Web geprobeerd."
    return "Web niet geprobeerd."


def should_attempt_web(web_mode: str, local_sufficient: bool, missing: list[str], confidence: str, answer_text: str = "") -> tuple[bool, str]:
    if web_mode not in WEB_MODES:
        web_mode = WEB_MODE_DEFAULT
    if web_mode == "off":
        return False, "web_disabled"
    if web_mode in {"enhance", "force"}:
        return True, "web_forced" if web_mode == "force" else "enhance_requested"
    insufficient_text = any(phrase in normalize_text(answer_text) for phrase in ["onvoldoende context", "ontbrekende bron", "geen betrouwbare definitie"])
    if (not local_sufficient) or missing or confidence == "low" or insufficient_text:
        return True, "local_context_insufficient"
    return False, "local_context_sufficient"


def attempt_web_context(query: str, fields: list[dict[str, Any]] | None, refs: list[str] | None, *, allow_external_web: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str], str]:
    try:
        result = build_web_context_with_candidates(query, matched_fields=fields or [], matched_terms=refs or [], allow_external_web=allow_external_web)
    except Exception:
        return [], [], [], [], "web_fetch_failed"
    context = result.get("web_context", [])
    candidates = result.get("web_candidates", [])
    rejected = result.get("rejected_web_candidates", [])
    strategies = result.get("web_discovery_strategies_used", [])
    if context:
        return context, candidates, rejected, strategies, "relevant_official_web_context_found"
    if candidates or rejected:
        return [], candidates, rejected, strategies, "no_relevant_official_web_context_found"
    return [], candidates, rejected, strategies, "no_free_official_web_context_found"


def web_debug_payload(*, requested: str, effective: str, attempted: bool, reason: str) -> dict[str, Any]:
    return {
        "web_mode_requested": requested,
        "web_mode_effective": effective,
        "web_attempted": attempted,
        "web_decision_reason": reason,
        "web_provider": "free_only",
        "web_provider_available": True,
    }


def bronstatus_labels(*, web_context: list[dict[str, Any]] | None = None, llm_inference: dict[str, Any] | None = None, has_supplemental: bool = False, manual_knowledge_used: bool = False, web_mode: str = WEB_MODE_DEFAULT, web_attempted: bool = False, web_decision_reason: str = "local_context_sufficient") -> list[str]:
    labels = ["Lokale officiële documentatie gebruikt."]
    if has_supplemental:
        labels.append("Aanvullende lokale documentatie gebruikt.")
    web_context = web_context or []
    if any(w.get("source_tier") == "official_web" and w.get("used_for_answer", True) for w in web_context):
        labels.append("Officiële webbronnen gebruikt.")
    if any(w.get("source_tier") == "external_web" for w in web_context):
        labels.append("Externe webbronnen gebruikt als lager geprioriteerde context.")
    if not web_context:
        labels.append("Geen webbronnen gebruikt.")
    if llm_inference and str(llm_inference.get("text") or "").strip():
        labels.append("LLM-interpretatie gebruikt.")
    labels.append(f"Webmodus: {web_mode_label(web_mode)}.")
    if web_attempted:
        labels.append("Web geprobeerd.")
    labels.append(web_decision_label(web_decision_reason, web_attempted, bool(web_context)))
    if not manual_knowledge_used:
        labels.append("Niet bevestigd door interne/mondelinge kennis.")
    return labels


def is_meaningful_llm_inference(llm_inference: dict[str, Any] | None) -> bool:
    if not llm_inference:
        return False
    text = normalize_text(llm_inference.get("text"))
    generic = normalize_text("Deze uitleg is een voorzichtige LLM-interpretatie op basis van de hierboven gelabelde bronlagen; bij conflicten blijft lokale officiële documentatie leidend.")
    return bool(text) and text != generic and "disclaimer" not in text


def build_llm_inference_text(query: str, official_answer: str, matched_fields: list[dict[str, Any]] | None = None, context_pack: dict[str, Any] | None = None, web_context: list[dict[str, Any]] | None = None, web_sources_used: bool | None = None) -> str:
    text = normalize_text(" ".join([query, official_answer]))
    web_sources_used = bool(web_context) if web_sources_used is None else web_sources_used
    web_blob = normalize_text(" ".join(str(w.get("title", "")) + " " + str(w.get("text_excerpt", "")) + " " + str(w.get("evidence_excerpt", "")) for w in (web_context or [])))
    if "onechte neveninschrijving" in text:
        interpretation = "Praktisch betekent dit waarschijnlijk dat de inschrijving administratief wel bestaat als neveninschrijving, maar voorzichtig geïnterpreteerd moet worden als zelfstandige extra inschrijving. De lokale documentatie zegt dat dezelfde combinatie van opleiding en instelling al voorkomt bij een andere inschrijving van dezelfde student."
        if web_sources_used and ("soort inschrijving ho" in web_blob or "rekenregel" in web_blob or "beslisboom" in web_blob or "duo" in web_blob or "dubbeltelling" in web_blob):
            interpretation += " De aanvullende DUO-bron plaatst dit binnen het veld `Soort inschrijving ho`, dat de status van een inschrijving in het HO-domein aangeeft. DUO beschrijft dit veld als afgeleid via een rekenregel/beslisboom, met als doel om dubbeltellingen van inschrijvingen te voorkomen."
        return interpretation
    if "echte neveninschrijving" in text:
        return "Praktisch betekent dit waarschijnlijk dat de inschrijving als afzonderlijke neveninschrijving kan meetellen, omdat de relevante combinatie niet al bij een andere inschrijving van dezelfde student voorkomt."
    if "hoofdinschrijving" in text:
        return "Praktisch betekent dit waarschijnlijk dat dit de inschrijving is die administratief als belangrijkste of eerst leidende inschrijving wordt behandeld binnen de betreffende telling."
    if "overige inschrijving" in text or "overige inschrijvingen" in text:
        return "Praktisch betekent dit waarschijnlijk dat de inschrijving niet in de hoofd- of specifieke neveninschrijvingscategorie valt en daarom apart en voorzichtig als restcategorie moet worden geïnterpreteerd."
    return ""


def build_llm_inference_disclaimer(web_sources_used: bool) -> str:
    if web_sources_used:
        return "Deze uitleg is een LLM-interpretatie op basis van lokale officiële documentatie en de hierboven getoonde officiële webbron(nen). Dit is geen bevestigde interne/mondelinge toelichting."
    return "Deze uitleg is een LLM-interpretatie op basis van lokale officiële documentatie. Dit is geen bevestigde interne/mondelinge toelichting."


def _disclaimer_for_tiers(based_on: list[str]) -> str:
    return build_llm_inference_disclaimer("official_web" in based_on or "external_web" in based_on)


def primary_aggregate_fields_for_term(term: Any, fields: list[str]) -> list[str]:
    if "onechte neveninschrijving" not in normalize_text(term):
        return fields
    catalog_names = [f["field_name"] for f in catalog_fields() if normalize_text(f.get("field_name", "")).startswith("soort inschrijving")]
    return catalog_names or [field for field in fields if normalize_text(field).startswith("soort inschrijving")]

def _local_context_sufficient(fields: list[dict[str, Any]], pack: dict[str, Any], refs: list[str]) -> bool:
    return bool(fields) and (not refs or bool(pack.get("supplemental_context")))


def _build_llm_inference(query: str, tiers: list[str], missing: list[str], allow_llm_inference: bool, *, official_answer: str = "", matched_fields: list[dict[str, Any]] | None = None, context_pack: dict[str, Any] | None = None, web_context: list[dict[str, Any]] | None = None, web_sources_used: bool | None = None) -> dict[str, Any] | None:
    if not allow_llm_inference:
        return None
    based_on = [tier for tier in tiers if tier != "llm_inference"]
    web_sources_used = bool(web_context) if web_sources_used is None else web_sources_used
    text = build_llm_inference_text(query, official_answer, matched_fields, context_pack, web_context, web_sources_used)
    if not text:
        return None
    if missing:
        text += " Ontbrekende broncontext blijft onzeker: " + ", ".join(missing) + "."
    return {
        "status": "unverified_interpretation",
        "based_on_sources": based_on,
        "text": text,
        "confidence": "low_to_medium",
        "disclaimer": build_llm_inference_disclaimer(web_sources_used),
    }


def answer_deep_context_question_json(
    query: str,
    source_focus: str = "primary",
    include_supplemental: bool = True,
    include_manual_knowledge: bool = True,
    allow_llm_inference: bool = True,
    web_mode: str = WEB_MODE_DEFAULT,
    official_web_only: bool = True,
    allow_external_web: bool = False,
    allow_web_sources: bool | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Answer source-aware field/context questions with references followed."""
    web_mode_requested = web_mode
    if allow_web_sources is not None:
        web_mode = "fallback" if allow_web_sources else "off"
    if web_mode not in WEB_MODES:
        web_mode = WEB_MODE_DEFAULT
    if official_web_only:
        allow_external_web = False
    q = normalize_text(query)
    fields = match_catalog_fields(query, limit=6)
    # Common elliptical comparison: "opleiding historisch" vs "opleiding actueel".
    if "opleiding" in q and "historisch" in q and "actueel" in q:
        wanted = {"Opleiding actueel equivalent", "Opleiding historisch equivalent"}
        by_name = {f["field_name"]: f for f in catalog_fields()}
        fields = [by_name[name] for name in wanted if name in by_name]
    if "internationale student" in q and ("verschil" in q or "peildatum" in q and "actueel" in q):
        wanted = ["Indicatie internationale student", "Indicatie internationale student op peildatum 1 oktober"]
        by_name = {f["field_name"]: f for f in catalog_fields()}
        fields = [by_name[name] for name in wanted if name in by_name]
    if not fields:
        payload = answer_definition_question_json(query, debug=debug, source_focus=source_focus, include_supplemental=include_supplemental)
        payload.setdefault("web_context", [])
        payload.setdefault("official_web_sources", [])
        payload.setdefault("web_candidates", [])
        payload.setdefault("rejected_web_candidates", [])
        payload.setdefault("web_sources_used", False)
        payload.setdefault("source_tiers_used", ["official_documentation"] if payload.get("curated_definition_found") else [])
        if allow_llm_inference:
            payload["llm_inference"] = _build_llm_inference(query, payload["source_tiers_used"], [], allow_llm_inference, official_answer=str(payload.get("definition") or payload.get("answer") or ""))
            if payload["llm_inference"]:
                payload["source_tiers_used"] = unique_preserve_order(payload["source_tiers_used"] + ["llm_inference"])
        payload["llm_inference_used"] = bool(payload.get("llm_inference"))
        local_sufficient = bool(payload.get("curated_definition_found") or payload.get("definition"))
        attempted, reason = should_attempt_web(web_mode, local_sufficient, [], "medium" if local_sufficient else "low", str(payload.get("answer", "")))
        web_context = []
        web_candidates = []
        rejected_web_candidates = []
        web_discovery_strategies_used = []
        if attempted:
            web_context, web_candidates, rejected_web_candidates, web_discovery_strategies_used, reason = attempt_web_context(query, [], [], allow_external_web=allow_external_web)
        payload["web_mode"] = web_mode
        payload["web_attempted"] = attempted
        payload["web_decision_reason"] = reason
        payload["web_context"] = web_context
        payload["official_web_sources"] = [w for w in web_context if w.get("source_tier") == "official_web"]
        payload["web_candidates"] = web_candidates
        payload["rejected_web_candidates"] = rejected_web_candidates
        payload["web_sources_used"] = any(w.get("used_for_answer", True) for w in web_context)
        if payload["web_sources_used"]:
            payload["source_tiers_used"] = unique_preserve_order(payload.get("source_tiers_used", []) + ["official_web"] + (["llm_inference"] if payload.get("llm_inference") else []))
            if allow_llm_inference:
                payload["llm_inference"] = _build_llm_inference(query, [tier for tier in payload["source_tiers_used"] if tier != "llm_inference"], [], allow_llm_inference, official_answer=str(payload.get("definition") or payload.get("answer") or ""), web_context=web_context, web_sources_used=True)
                payload["llm_inference_used"] = bool(payload.get("llm_inference"))
        payload["web_discovery_strategies_used"] = web_discovery_strategies_used
        payload["bronstatus"] = bronstatus_labels(web_context=web_context, llm_inference=payload.get("llm_inference"), web_mode=web_mode, web_attempted=attempted, web_decision_reason=reason)
        if debug:
            payload.setdefault("debug", {})["web_decision"] = web_debug_payload(requested=web_mode_requested, effective=web_mode, attempted=attempted, reason=reason)
        return payload

    if "verwijs" in q or "verwijzing" in q or "waar naar" in q:
        intent = "field_reference"
        exact = find_catalog_field(query)
        if exact is not None:
            fields = [exact["field_detail"]]
        else:
            fields = fields[:1]
    elif "verschil" in q or len(fields) > 1:
        intent = "field_comparison"
    elif "waarde" in q or "waarden" in q:
        intent = "field_values"
    else:
        intent = "field_detail"

    pack = build_context_pack(query, fields, include_supplemental=include_supplemental)
    refs = sorted({r for f in fields for r in (f.get("references") or [])}, key=str.lower)
    has_supp = bool(pack["supplemental_context"])
    missing = pack["missing_references"]
    local_sufficient = _local_context_sufficient(fields, pack, refs)
    confidence = "high" if has_supp else ("medium" if not refs else "low")
    web_attempted, web_decision_reason = should_attempt_web(web_mode, local_sufficient, missing, confidence)
    web_context = []
    web_candidates = []
    rejected_web_candidates = []
    web_discovery_strategies_used = []
    web_unavailable_message = ""
    if web_attempted:
        web_context, web_candidates, rejected_web_candidates, web_discovery_strategies_used, web_decision_reason = attempt_web_context(query, fields, refs, allow_external_web=allow_external_web)
        if not web_context:
            web_unavailable_message = "Geen bruikbare officiële webbron gevonden." if web_decision_reason == "no_relevant_official_web_context_found" else "Geen gratis officiële webbron gevonden/gebruikt."
    official_web = [w for w in web_context if w.get("source_tier") == "official_web"]
    external_web = [w for w in web_context if w.get("source_tier") == "external_web"]
    source_tiers_used = ["official_documentation"]
    if has_supp:
        source_tiers_used.append("official_supplemental")
    if official_web:
        source_tiers_used.append("official_web")
    if external_web:
        source_tiers_used.append("external_web")
    official_answer_summary = " ".join([str(f.get("description", "")) for f in fields])
    web_sources_used = any(w.get("used_for_answer", True) for w in web_context)
    llm_inference = _build_llm_inference(query, source_tiers_used, missing, allow_llm_inference, official_answer=official_answer_summary, matched_fields=fields, context_pack=pack, web_context=web_context, web_sources_used=web_sources_used)
    if llm_inference:
        source_tiers_used.append("llm_inference")
    lines = ["Antwoord:", "Uit lokale officiële documentatie:"]
    for field in fields:
        lines.append(f"- {field['field_name']} (veld {field['field_number']}): {field.get('description','')}")
        if field.get("possible_values"):
            lines.extend([f"  - {v.get('code')} = {v.get('meaning')}" for v in field["possible_values"]])
        if field.get("notes"):
            lines.extend([f"  - NB: {n}" for n in field["notes"]])
    if refs:
        lines += ["", "Verwijzingen naar andere documentatie:"] + [f"- Bestandsbeschrijving {r}" if r.startswith("hoacth") else f"- {r}" for r in refs]
    if has_supp:
        lines += ["", "Aanvullende lokale documentatie:"] + [f"- {c.get('source_document')}: {c.get('text')}" for c in pack["supplemental_context"][:2]]
    elif refs:
        lines += ["", "Aanvullende lokale documentatie:", "- Er is geen aanvullende broncontext gevonden in de huidige repo/chunk-index voor deze verwijzingen."]
    if official_web or web_unavailable_message:
        lines += ["", "Uit officiële webbronnen:"]
        lines += [f"- {w.get('title')} ({w.get('domain')}): {w.get('text_excerpt')}" for w in official_web[:3]] or [f"- {web_unavailable_message}"]
    if external_web:
        lines += ["", "Let op: onderstaande aanvullende context komt uit externe webbronnen en is lager geprioriteerd dan officiële documentatie.", "Externe webbronnen:"]
        lines += [f"- {w.get('title')} ({w.get('domain')}): {w.get('text_excerpt')}" for w in external_web[:3]]
    if llm_inference:
        lines += ["", "LLM-interpretatie:", llm_inference["text"]]
    if missing:
        lines += ["", "Onzekerheid of ontbrekende bron:"] + [f"- {r}" for r in missing]
    if intent == "field_comparison":
        if {f["field_name"] for f in fields} == {"Opleiding actueel equivalent", "Opleiding historisch equivalent"} and not has_supp:
            lines += ["", "Conclusie / verschil:", "Het primaire document toont dat beide opleidingsvelden bestaan, maar bevat zelf alleen de verwijzing naar Bestandsbeschrijving hoacth.csv/hoacth_vest.csv. Daardoor kan het inhoudelijke verschil niet volledig uit het primaire document alleen worden verklaard."]
        elif any("internationale student" in normalize_text(f["field_name"]) for f in fields):
            lines += ["", "Conclusie / verschil:", "De actuele variant gebruikt de actuele eerste nationaliteit en kan door naturalisatie met terugwerkende kracht wijzigen. De peildatumvariant gebruikt de eerste nationaliteit op peildatum 1 oktober; jaren vóór naturalisatie blijven als internationale student geregistreerd als dat toen zo was. In beide gevallen hoort bij de kern dat de student geen Nederlandse nationaliteit en geen Nederlandse vooropleiding vóór het HO heeft."]
    if not any(line == "Bronstatus:" for line in lines):
        lines += ["", "Bronstatus:"] + [f"- {label}" for label in bronstatus_labels(web_context=web_context, llm_inference=llm_inference, has_supplemental=has_supp, manual_knowledge_used=False, web_mode=web_mode, web_attempted=web_attempted, web_decision_reason=web_decision_reason)]
    answer = "\n".join(lines)
    payload = {
        "query": query,
        "intent": intent,
        "answer": answer,
        "matched_fields": [{k: f.get(k) for k in ["field_number", "field_name", "description", "source_document", "source_path", "references", "dataset", "bron", "type_field", "possible_values", "notes"]} for f in fields],
        "field_detail": fields[0] if len(fields) == 1 else None,
        "field_details": fields,
        "primary_source_used": True,
        "source_policy": "supplemental_used" if has_supp else "primary_only",
        "supplemental_sources_used": pack["supplemental_sources_used"],
        "supplemental_context": pack["supplemental_context"],
        "supplemental_sources": pack["supplemental_sources_used"],
        "missing_references": missing,
        "references": refs,
        "confidence": confidence,
        "evidence": pack["primary_evidence"] + pack["supplemental_context"],
        "context_pack": pack,
        "datasets": [PRIMARY_DATASET],
        "fields": [f["field_name"] for f in fields],
        "notes": [n for f in fields for n in (f.get("notes") or [])],
        "primary_source_document": PRIMARY_SOURCE_DOCUMENT,
        "source_tiers": SOURCE_TIERS,
        "web_mode": web_mode,
        "web_attempted": web_attempted,
        "web_decision_reason": web_decision_reason,
        "web_sources_used": any(w.get("used_for_answer", True) for w in web_context),
        "web_context": web_context,
        "official_web_sources": [w for w in web_context if w.get("source_tier") == "official_web"],
        "web_candidates": web_candidates,
        "rejected_web_candidates": rejected_web_candidates,
        "web_discovery_strategies_used": web_discovery_strategies_used,
        "source_tiers_used": unique_preserve_order(source_tiers_used),
        "llm_inference": llm_inference,
        "llm_inference_used": bool(llm_inference),
        "bronstatus": bronstatus_labels(web_context=web_context, llm_inference=llm_inference, has_supplemental=has_supp, manual_knowledge_used=False, web_mode=web_mode, web_attempted=web_attempted, web_decision_reason=web_decision_reason),
        "manual_knowledge_used": False,
        "web_unavailable_message": web_unavailable_message,
    }
    if debug:
        payload["debug"] = {"matched_field_scores": [(field_term_score(query, f), f["field_name"]) for f in fields], "web_decision": web_debug_payload(requested=web_mode_requested, effective=web_mode, attempted=web_attempted, reason=web_decision_reason)}
    return payload

def detect_intent(query: str) -> str:
    """Classify intents, including primary inschrijvingen field-catalog intents."""
    normalized = normalize_text(query)
    if is_all_fields_query(query):
        return "all_fields"
    if "verschil" in normalized or "vergelijk" in normalized:
        return "field_comparison"
    if any(p in normalized for p in ("welke records", "records geselecteerd", "waarop is het bestand gebaseerd", "selectie")):
        return "source_selection"
    if any(p in normalized for p in ("bewerking", "bewerkingen", "transformatie", "waarde 6")):
        return "transformation"
    if any(p in normalized for p in ("waar verwijst", "verwijst", "verwijzing", "verwijzingen")):
        return "field_reference"
    if any(p in normalized for p in ("mogelijke waarden", "welke waarden", "wat betekent code", "waarde ")):
        return "field_values"
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
    if "onechte neveninschrijving" in normalize_text(title):
        definition = definition.replace("sleutel-domeinvelden en soort-inschrijvingsvelden", "soort-inschrijvingsvelden")
    fields = primary_aggregate_fields_for_term(title, filter_fields_for_main_term(title, [field for field in sanitize_fields(metadata_values(group, "fields") + group["fields"]) if normalize_text(field) != normalize_text(title)]))
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


def answer_definition_question_json(query: str, debug: bool = False, source_focus: str = "primary", include_supplemental: bool = True, web_mode: str = WEB_MODE_DEFAULT) -> dict[str, Any]:
    """Return structured retrieval output for LLM/chatbot grounding.

    The JSON-style dictionary separates the user query, detected intent, final
    answer text, selected definition, fields, datasets, notes and related terms.
    A future LLM should treat this payload as source material and avoid adding
    unsupported definitions from its own prior knowledge.
    """
    web_mode_requested = web_mode
    if web_mode not in WEB_MODES:
        web_mode = WEB_MODE_DEFAULT
    intent = detect_intent(query)
    primary_relevant = source_focus == "primary" and (is_primary_query(query) or intent in {"field_comparison", "field_reference", "field_values"} or bool(match_catalog_fields(query, limit=2)))
    source_policy = "primary_preferred" if primary_relevant else "no_difference"
    if primary_relevant and intent in {"all_fields", "dataset_layout"}:
        return build_all_fields_payload(query, debug, "primary_only")
    if primary_relevant and intent in {"field_comparison", "field_reference", "field_values"} and match_catalog_fields(query, limit=1):
        return answer_deep_context_question_json(query, source_focus=source_focus, include_supplemental=include_supplemental, debug=debug, web_mode=web_mode)
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
                "definition": best_definition(group).replace("sleutel-domeinvelden en soort-inschrijvingsvelden", "soort-inschrijvingsvelden") if "onechte neveninschrijving" in normalize_text(group["best"]["entry"].get("term")) else best_definition(group),
                "fields": primary_aggregate_fields_for_term(group["best"]["entry"].get("term", ""), filter_fields_for_main_term(group["best"]["entry"].get("term", ""), [
                    field
                    for field in sanitize_fields(metadata_values(group, "fields") + group["fields"])
                    if normalize_text(field) != normalize_text(group["best"]["entry"].get("term", ""))
                ])),
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

    if payload.get("curated_definition_found"):
        tiers = ["official_documentation"]
        attempted, reason = should_attempt_web(web_mode, True, [], "medium", str(payload.get("answer", "")))
        web_context = []
        web_candidates = []
        rejected_web_candidates = []
        web_discovery_strategies_used = []
        if attempted:
            web_context, web_candidates, rejected_web_candidates, web_discovery_strategies_used, reason = attempt_web_context(query, [], [], allow_external_web=False)
        web_based_tiers = unique_preserve_order(tiers + (["official_web"] if any(w.get("source_tier") == "official_web" for w in web_context) else []) + (["external_web"] if any(w.get("source_tier") == "external_web" for w in web_context) else []))
        web_sources_used = any(w.get("used_for_answer", True) for w in web_context)
        llm = _build_llm_inference(query, web_based_tiers, [], True, official_answer=str(payload.get("definition") or payload.get("answer") or ""), web_context=web_context, web_sources_used=web_sources_used)
        if llm:
            llm["based_on_sources"] = web_based_tiers
            llm["disclaimer"] = build_llm_inference_disclaimer(web_sources_used)
        source_tiers = unique_preserve_order(web_based_tiers + (["llm_inference"] if llm else []))
        payload.update({
            "web_mode": web_mode,
            "web_attempted": attempted,
            "web_decision_reason": reason,
            "web_context": web_context,
            "official_web_sources": [w for w in web_context if w.get("source_tier") == "official_web"],
            "web_candidates": web_candidates,
            "rejected_web_candidates": rejected_web_candidates,
            "web_sources_used": any(w.get("used_for_answer", True) for w in web_context),
            "web_discovery_strategies_used": web_discovery_strategies_used,
            "source_tiers_used": source_tiers,
            "llm_inference": llm,
            "llm_inference_used": bool(llm),
            "bronstatus": bronstatus_labels(web_context=web_context, llm_inference=llm, web_mode=web_mode, web_attempted=attempted, web_decision_reason=reason),
        })
        if llm:
            payload["answer"] = payload["answer"].rstrip() + "\n\nLLM-interpretatie:\n" + llm["text"] + "\n\nBronstatus:\n" + "\n".join(f"- {label}" for label in payload["bronstatus"])
    else:
        payload.setdefault("web_mode", web_mode)
        payload.setdefault("web_attempted", False)
        payload.setdefault("web_decision_reason", "web_disabled" if web_mode == "off" else "local_context_sufficient")
        payload.setdefault("web_context", [])
        payload.setdefault("official_web_sources", [])
        payload.setdefault("web_candidates", [])
        payload.setdefault("rejected_web_candidates", [])
        payload.setdefault("web_sources_used", False)
        payload.setdefault("source_tiers_used", [])
        payload.setdefault("llm_inference", None)
        payload.setdefault("llm_inference_used", False)
        payload.setdefault("bronstatus", bronstatus_labels(web_context=[], llm_inference=None, web_mode=web_mode, web_attempted=False, web_decision_reason=payload["web_decision_reason"]))

    if debug:
        payload["debug_matches"] = [debug_match_payload(result) for result in results]
        payload.setdefault("debug", {})["web_decision"] = web_debug_payload(requested=web_mode_requested, effective=web_mode, attempted=bool(payload.get("web_attempted")), reason=str(payload.get("web_decision_reason")))

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

