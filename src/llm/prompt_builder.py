"""Build compact, strictly grounded prompts for the optional LLM layer.

The prompt used to be the entire retrieval payload dumped as JSON. That payload
repeats the same field information in ``matched_fields``, ``field_detail``,
``field_details``, ``context_pack`` and ``evidence``, so a single question could
produce a prompt of 10.000+ tokens. On a local CPU model that is minutes of
prompt processing before the first token appears, and it can even push the
grounding rules out of the model's context window.

This module therefore sends the facts once, in readable Dutch, with hard limits
per section. The rules are unchanged: the model formulates, it never adds facts.
"""

from __future__ import annotations

from typing import Any, Iterable

# Budgets keep a local model responsive; raising them costs latency directly.
MAX_DEFINITION_CHARS = 900
MAX_SUMMARY_CHARS = 800
MAX_FIELDS = 10
MAX_DATASETS = 8
MAX_NOTES = 4
MAX_NOTE_CHARS = 300
MAX_MATCHED_FIELDS = 3
MAX_FIELD_DESCRIPTION_CHARS = 500
MAX_VALUES_PER_FIELD = 8
MAX_EXCERPTS = 2
MAX_EXCERPT_CHARS = 400
# Hard ceiling on the grounded facts; a local model pays for every token here.
MAX_CONTEXT_CHARS = 4000
MAX_PROMPT_CHARS = 6000

RULES = """Regels:
- Gebruik uitsluitend de brongegevens hierboven; verzin geen definities, velden, databestanden of aandachtspunten.
- Staat iets er niet bij, zeg dan dat het niet in de beschikbare documentatie staat.
- Neem belangrijke nuances en NB's uit "Let op" mee.
- Ontbrekende bronnen benoem je als onzekerheid, met de naam van de bron die nodig is.
- Lokale officiële documentatie is leidend; webbronnen en semantische fragmenten zijn aanvullend en label je als zodanig.
- Semantische fragmenten zijn zoekresultaten, geen vastgestelde definitie.
- Antwoord in helder, beknopt Nederlands (maximaal ongeveer 200 woorden)."""

DEEP_CONTEXT_RULE = (
    '- Gebruik de kopjes "Uit het primaire document", "Aanvullende context", '
    '"Conclusie / verschil" en, indien relevant, "Onzekerheid of ontbrekende bron".'
)


def _clean(value: Any, limit: int) -> str:
    """Collapse whitespace and cut to ``limit`` characters."""
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _bullets(values: Iterable[Any], limit: int, *, item_chars: int = 120) -> str:
    items = [_clean(value, item_chars) for value in list(values)[:limit]]
    return ", ".join(item for item in items if item)


def _section(title: str, body: str) -> str:
    return f"{title}: {body}" if body else ""


def field_lines(
    matched_fields: list[dict[str, Any]],
    *,
    limit: int = MAX_MATCHED_FIELDS,
    description_chars: int = MAX_FIELD_DESCRIPTION_CHARS,
) -> list[str]:
    """Render matched catalog fields once, with their values and notes trimmed."""
    lines: list[str] = []
    for field in matched_fields[:limit]:
        name = _clean(field.get("field_name"), 120)
        if not name:
            continue
        lines.append(f"- {name}: {_clean(field.get('description'), description_chars)}")
        values = field.get("possible_values") or []
        rendered = []
        for value in values[:MAX_VALUES_PER_FIELD]:
            if isinstance(value, dict):
                code = _clean(value.get("value") or value.get("code"), 40)
                meaning = _clean(value.get("meaning") or value.get("description"), 80)
                rendered.append(f"{code} = {meaning}" if meaning else code)
            else:
                rendered.append(_clean(value, 80))
        if rendered:
            lines.append(f"  Mogelijke waarden: {'; '.join(item for item in rendered if item)}")
        notes = [_clean(note, MAX_NOTE_CHARS) for note in (field.get("notes") or [])[:2]]
        for note in notes:
            if note:
                lines.append(f"  NB: {note}")
    return lines


def excerpt_lines(
    title: str,
    entries: list[dict[str, Any]],
    *,
    label_key: str,
    text_keys: tuple[str, ...],
    limit: int = MAX_EXCERPTS,
    chars: int = MAX_EXCERPT_CHARS,
) -> list[str]:
    """Render a few short source excerpts under one heading."""
    lines: list[str] = []
    for entry in entries[:limit]:
        text = ""
        for key in text_keys:
            text = _clean(entry.get(key), chars)
            if text:
                break
        if not text:
            continue
        label = _clean(entry.get(label_key) or entry.get("term") or entry.get("url"), 120)
        page = f", p. {entry['page']}" if entry.get("page") else ""
        lines.append(f"- {label}{page}: {text}")
    return [f"{title}:", *lines] if lines else []


def summary_from_answer(answer: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Return the composed answer text without its status/interpretation blocks."""
    lines: list[str] = []
    for line in str(answer or "").splitlines():
        if line.strip() in {"Bronstatus:", "LLM-interpretatie:"}:
            break
        lines.append(line)
    return _clean("\n".join(lines), limit)


def build_context_block(retrieval_result: dict[str, Any], *, tight: bool = False) -> str:
    """Return the grounded facts of one retrieval payload, deduplicated.

    ``tight`` halves the per-section budgets for payloads that would otherwise
    produce a slow prompt; the same sections are kept, with shorter excerpts.
    """
    scale = 0.5 if tight else 1.0
    definition_chars = int(MAX_DEFINITION_CHARS * scale)
    summary_chars = int(MAX_SUMMARY_CHARS * scale)
    description_chars = int(MAX_FIELD_DESCRIPTION_CHARS * scale)
    excerpts = 1 if tight else MAX_EXCERPTS
    excerpt_chars = int(MAX_EXCERPT_CHARS * scale)
    matched_limit = 2 if tight else MAX_MATCHED_FIELDS
    parts: list[str] = []

    matched_fields = retrieval_result.get("matched_fields") or []
    main_term = _clean(retrieval_result.get("main_term"), 120)
    if not main_term and matched_fields:
        main_term = _clean(matched_fields[0].get("field_name"), 120)
    definition = _clean(retrieval_result.get("definition"), definition_chars)

    parts.append(_section("Onderwerp", main_term))
    parts.append(_section("Definitie uit de documentatie", definition))
    if not definition:
        # No separate definition: the retrieval layer's own composed answer is the
        # grounded summary. Its status blocks are dropped; they are not content.
        parts.append(_section("Samenvatting uit de documentatie", summary_from_answer(retrieval_result.get("answer"), summary_chars)))
    parts.append(_section("Relevante velden", _bullets(retrieval_result.get("fields") or [], MAX_FIELDS)))
    parts.append(_section("Databestanden", _bullets(retrieval_result.get("datasets") or [], MAX_DATASETS)))

    notes = [_clean(note, MAX_NOTE_CHARS) for note in (retrieval_result.get("notes") or [])[:MAX_NOTES]]
    notes = [note for note in notes if note]
    if notes:
        parts.append("Let op:\n" + "\n".join(f"- {note}" for note in notes))

    matched = field_lines(matched_fields, limit=matched_limit, description_chars=description_chars)
    if matched:
        parts.append("Velden uit het primaire document:\n" + "\n".join(matched))

    supplemental = excerpt_lines(
        "Aanvullende lokale documentatie",
        retrieval_result.get("supplemental_context") or [],
        label_key="source_document",
        text_keys=("text", "preview"),
        limit=excerpts,
        chars=excerpt_chars,
    )
    if supplemental:
        parts.append("\n".join(supplemental))

    semantic = excerpt_lines(
        "Semantisch gevonden fragmenten (zoekresultaat, geen definitie)",
        retrieval_result.get("semantic_context") or [],
        label_key="source_document",
        text_keys=("preview", "text"),
        limit=excerpts,
        chars=excerpt_chars,
    )
    if semantic:
        parts.append("\n".join(semantic))

    web_sources = retrieval_result.get("official_web_sources") or retrieval_result.get("web_context") or []
    web = excerpt_lines(
        "Officiële webbronnen",
        web_sources,
        label_key="title",
        text_keys=("evidence_excerpt", "text_excerpt"),
        limit=excerpts,
        chars=excerpt_chars,
    )
    if web:
        parts.append("\n".join(web))

    parts.append(_section("Verwijzingen naar andere documentatie", _bullets(retrieval_result.get("references") or [], 6)))
    parts.append(_section("Ontbrekende bronnen", _bullets(retrieval_result.get("missing_references") or [], 6)))

    return "\n\n".join(part for part in parts if part)


def format_history(history: Any) -> str:
    """Render the last turns compactly, only to resolve backreferences."""
    from src.conversation.context import format_history_for_prompt

    return format_history_for_prompt(history or [])


def build_grounded_prompt(user_query: str, retrieval_result: dict, history: Any = None) -> str:
    """Return a compact Dutch prompt grounded only in the retrieval result.

    A second, tighter pass runs when a rich deep-context answer would still push
    the prompt over ``MAX_PROMPT_CHARS``; the facts stay, their excerpts shrink.
    """
    context = build_context_block(retrieval_result or {})
    if len(context) > MAX_CONTEXT_CHARS:
        context = build_context_block(retrieval_result or {}, tight=True)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS].rstrip() + "\n[... ingekort om het lokale model snel te houden]"
    conversation = format_history(history)
    rules = RULES
    if (retrieval_result or {}).get("matched_fields"):
        rules = f"{RULES}\n{DEEP_CONTEXT_RULE}"

    blocks = [
        "Je bent een assistent voor Nederlandse hoger-onderwijsdata (1cijferHO).",
        conversation,
        f"Vraag van de gebruiker:\n{_clean(user_query, 500)}",
        f"Brongegevens uit de lokale officiële documentatie:\n{context}" if context
        else "Brongegevens: geen passende documentatie gevonden.",
        rules,
        "Antwoord:",
    ]
    return "\n\n".join(block for block in blocks if block)
