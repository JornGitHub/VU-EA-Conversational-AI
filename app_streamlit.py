"""Streamlit UI for the reusable HO definition retrieval module.

Install and run manually with:
    pip install streamlit
    streamlit run app_streamlit.py
"""

import json

import streamlit as st

from src.chatbot import answer_with_llm
from src.definitions.search import answer_deep_context_question_json, answer_definition_question_json


EXAMPLE_QUESTIONS = [
    "Wat is een internationale student?",
    "Wat betekent Indicatie internationale student?",
    "Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?",
    "Wat is het verschil tussen opleiding historisch en opleiding actueel?",
    "Wat betekent Opleiding actueel equivalent?",
    "Waar verwijst Opleiding historisch equivalent naar?",
    "Welke waarden heeft Indicatie actief op peildatum?",
    "Toon alle velden van Inschrijvingen_aggr_UNL_2025.csv",
]


st.set_page_config(
    page_title="HO Definitiezoeker",
    page_icon="📘",
    layout="centered",
)


def display_topic(main_term: str | None) -> str:
    """Return natural Dutch topic wording for location answers."""
    if not main_term:
        return "dit onderwerp"

    normalized = main_term.strip().lower()
    special_cases = {
        "internationale student": "internationale studenten",
        "student / ingeschrevene": "studenten/ingeschrevenen",
        "student/ingeschrevene": "studenten/ingeschrevenen",
    }
    return special_cases.get(normalized, normalized)


def format_definition_topic(main_term: str | None) -> str:
    """Return a concise singular-ish topic label for definition answers."""
    if not main_term:
        return ""

    normalized = normalize_text(main_term)
    special_cases = {
        "internationale student": "internationale student",
        "student / ingeschrevene": "student/ingeschrevene",
        "student/ingeschrevene": "student/ingeschrevene",
    }
    return special_cases.get(normalized, normalized.replace(" / ", "/"))


def normalize_text(text: str | None) -> str:
    """Normalize text for simple UI-level intent and duplicate checks."""
    return " ".join(str(text or "").lower().strip().split())


def is_definition_like_query(query: str | None, result: dict) -> bool:
    """Return True when the UI should present the answer as a definition."""
    normalized_query = normalize_text(query)
    definition_phrases = (
        "wat is",
        "wat betekent",
        "definitie",
        "wat telt als",
        "wanneer telt",
        "wat wordt geteld als",
    )
    return result.get("intent") == "definition" or any(
        phrase in normalized_query for phrase in definition_phrases
    )


def render_definition_answer(main_term: str | None, definition: str) -> str:
    """Render and return the definition answer body shown in the UI."""
    topic = format_definition_topic(main_term)
    if topic:
        st.markdown(f"**Definitie van {topic}:**")
    else:
        st.markdown("**Definitie:**")
    st.markdown(definition)
    return definition


def render_bullets(values: list[str], *, code: bool = False) -> None:
    """Render a list as Markdown bullets, optionally formatting values as code."""
    for value in values:
        if code:
            st.markdown(f"- `{value}`")
        else:
            st.markdown(f"- {value}")


def render_result(result: dict, *, show_source_status: bool = True) -> None:
    """Render structured retrieval output in clear Streamlit sections."""
    if result.get("curated_definition_found") is True:
        st.success("✅ Opgeschoonde definitie gevonden")
    else:
        st.warning(
            "⚠️ Geen opgeschoonde definitie gevonden; antwoord gebaseerd op "
            "documentatiefragmenten."
        )

    intent = result.get("intent")
    definition = str(result.get("definition") or "").strip()
    datasets = result.get("datasets") or []
    fields = result.get("fields") or []
    notes = result.get("notes") or []
    related_terms = result.get("related_terms") or []

    if result.get("primary_source_used"):
        st.info(f"Primaire bron gebruikt: {result.get('primary_source_document')}")
    if result.get("source_policy") == "no_difference":
        st.caption("Bronfocus maakt voor deze vraag inhoudelijk geen verschil; voorkeursranking blijft actief waar relevant.")
    if result.get("supplemental_sources"):
        st.warning("Aanvullende context uit andere documenten is gebruikt.")

    st.subheader("Antwoord")
    datasets_shown_in_answer = False
    if is_definition_like_query(result.get("query"), result) and definition:
        rendered_answer_body = render_definition_answer(
            result.get("main_term"), definition
        )
    elif intent == "location" and datasets:
        topic = display_topic(result.get("main_term"))
        rendered_answer_body = (
            f"Je vindt data over {topic} vooral in de volgende bestanden:"
        )
        st.markdown(rendered_answer_body)
        render_bullets(datasets, code=True)
        datasets_shown_in_answer = True
    elif definition:
        rendered_answer_body = definition
        st.markdown(rendered_answer_body)
    else:
        rendered_answer_body = result.get(
            "answer", "Ik heb geen passende definitie of veldbeschrijving gevonden."
        )
        st.markdown(rendered_answer_body)

    show_datasets_section = bool(datasets) and not datasets_shown_in_answer
    if show_datasets_section:
        st.subheader("Bestanden")
        render_bullets(datasets, code=True)

    definition_repeated_in_answer = (
        bool(definition)
        and normalize_text(definition) in normalize_text(rendered_answer_body)
    )
    show_definition_section = (
        bool(definition) and intent != "definition" and not definition_repeated_in_answer
    )
    if show_definition_section:
        st.subheader("Definitie")
        st.markdown(definition)

    if result.get("matched_fields"):
        st.subheader("Lokale officiële documentatie")
        for field in result["matched_fields"]:
            st.markdown(f"- **{field.get('field_name')}**: {field.get('description')}")
    if result.get("supplemental_context"):
        st.subheader("Aanvullende lokale documentatie")
        for chunk in result["supplemental_context"]:
            st.markdown(f"- `{chunk.get('source_document')}`: {str(chunk.get('text',''))[:300]}")
    web_context = result.get("web_context") or []
    official_web = [w for w in web_context if w.get("source_tier") == "official_web"]
    external_web = [w for w in web_context if w.get("source_tier") == "external_web"]
    if official_web or result.get("web_unavailable_message"):
        st.subheader("Officiële webbronnen")
        if not official_web:
            st.info(result.get("web_unavailable_message") or "Geen officiële webbronnen gebruikt.")
        for source in official_web:
            st.markdown(f"- **{source.get('title')}** — `{source.get('domain')}` — {source.get('retrieved_at')} — `{source.get('source_tier')}`")
            st.caption(source.get("url", ""))
            st.write(str(source.get("text_excerpt", ""))[:500])
    if external_web:
        st.subheader("Externe webbronnen")
        st.warning("Externe webbronnen zijn lager geprioriteerd dan officiële documentatie.")
        for source in external_web:
            st.markdown(f"- **{source.get('title')}** — `{source.get('domain')}` — {source.get('retrieved_at')} — `{source.get('source_tier')}`")
            st.caption(source.get("url", ""))
            st.write(str(source.get("text_excerpt", ""))[:500])
    if result.get("llm_inference"):
        st.subheader("LLM-interpretatie")
        st.write(result["llm_inference"].get("text"))
        st.caption(result["llm_inference"].get("disclaimer"))
    if show_source_status:
        st.subheader("Bronstatus")
        render_bullets(result.get("source_tiers_used") or [])
        if not result.get("manual_knowledge_used"):
            st.caption("Niet bevestigd door interne/mondelinge kennis.")

    if result.get("references"):
        st.subheader("Verwijzingen naar andere documentatie")
        render_bullets(result["references"], code=True)
    if result.get("missing_references"):
        st.subheader("Ontbrekende bronnen")
        render_bullets(result["missing_references"], code=True)

    if result.get("field_table"):
        st.subheader("Veldenoverzicht")
        st.dataframe(result["field_table"], use_container_width=True)
        st.download_button("Download velden als JSON", data=json.dumps(result["field_table"], ensure_ascii=False, indent=2), file_name="inschrijvingen_aggr_2025_fields.json", mime="application/json")
    if result.get("field_detail"):
        fd = result["field_detail"]
        st.subheader("Veldkaart")
        st.json({k: fd.get(k) for k in ["field_number", "field_name", "bron", "type_field", "dataset", "source_document", "source_path"]})
        if fd.get("possible_values"):
            st.subheader("Mogelijke waarden")
            st.table(fd["possible_values"])
        if fd.get("notes"):
            st.subheader("Let op / NB")
            render_bullets(fd["notes"])
        if fd.get("transformations"):
            st.subheader("Bewerkingen / afleidingen")
            render_bullets(fd["transformations"])
        if fd.get("related_fields"):
            st.subheader("Gerelateerde velden")
            render_bullets(fd["related_fields"], code=True)
    elif fields:
        st.subheader("Relevante velden")
        render_bullets(fields, code=True)

    if notes:
        st.subheader("Let op")
        render_bullets(notes)

    if related_terms:
        st.subheader("Andere mogelijke relevante begrippen")
        render_bullets(related_terms)

    with st.expander("Ruwe tekstversie"):
        st.markdown(result.get("answer", ""))


st.title("📘 HO Definitiezoeker")
st.markdown("Stel een vraag over definities, velden of databestanden uit de HO-documentatie.")

debug = st.sidebar.checkbox("Toon debug-informatie")
use_official_web = st.sidebar.checkbox("Gebruik officiële webbronnen", value=True)
use_external_web = st.sidebar.checkbox("Gebruik overige externe webbronnen", value=False)
allow_llm_inference = st.sidebar.checkbox("Sta LLM-interpretatie toe", value=True)
show_source_status = st.sidebar.checkbox("Toon bronstatus", value=True)
use_llm = st.sidebar.checkbox("Gebruik LLM-formuleerlaag", value=False)
model = st.sidebar.text_input("Ollama-model", value="qwen3:8b")
focus_primary = st.sidebar.checkbox("Focus op Aggregaatbestand inschrijvingen_1cHO2025.docx", value=True)
include_supplemental = st.sidebar.checkbox("Volg verwijzingen naar aanvullende documentatie", value=True)
use_deep_context = st.sidebar.checkbox("Gebruik LLM voor deep-context antwoorden", value=True)

if "query" not in st.session_state:
    st.session_state.query = ""

with st.expander("Voorbeeldvragen"):
    for question in EXAMPLE_QUESTIONS:
        if st.button(question):
            st.session_state.query = question

query = st.text_input("Stel een vraag over de HO-documentatie:", key="query")

if not query.strip():
    st.info("Voer een vraag in om te zoeken in de definitiebestanden.")
else:
    if use_llm:
        with st.spinner("Antwoord formuleren met LLM..."):
            result = answer_with_llm(query, model=model, debug=debug, source_focus="primary" if focus_primary else "auto", include_supplemental=include_supplemental, deep_context=use_deep_context, allow_web_sources=use_official_web, allow_external_web=use_external_web, allow_llm_inference=allow_llm_inference)

        if result.get("llm_answer"):
            st.subheader("LLM-antwoord")
            st.markdown(result["llm_answer"])
        else:
            st.error("De LLM kon geen antwoord genereren.")
            st.write(result.get("error", "Onbekende fout."))

        with st.expander("Gebruikte retrieval-output"):
            st.json(result["retrieval_result"])

        if debug and result.get("prompt"):
            with st.expander("Gebruikte prompt"):
                st.code(result["prompt"])
    else:
        try:
            result = answer_deep_context_question_json(query, debug=debug, source_focus="primary" if focus_primary else "auto", include_supplemental=include_supplemental, allow_web_sources=use_official_web, allow_external_web=use_external_web, allow_llm_inference=allow_llm_inference) if use_deep_context else answer_definition_question_json(query, debug=debug, source_focus="primary" if focus_primary else "auto", include_supplemental=include_supplemental)
        except Exception as exc:  # noqa: BLE001 - show useful diagnostics during development.
            st.error("Er ging iets mis bij het zoeken in de definitiebestanden.")
            st.exception(exc)
        else:
            render_result(result, show_source_status=show_source_status)
            if debug:
                with st.expander("Debug JSON"):
                    st.json(result)
