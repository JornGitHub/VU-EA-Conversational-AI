"""Streamlit UI for the reusable HO definition retrieval module.

Install and run manually with:
    pip install streamlit
    streamlit run app_streamlit.py
"""

import streamlit as st

from src.definitions.search import answer_definition_question_json


EXAMPLE_QUESTIONS = [
    "wat is een internationale student?",
    "waar vind ik data over internationale studenten?",
    "wat telt als student?",
    "wat is instroom?",
    "wat is studiesucces?",
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


def render_result(result: dict) -> None:
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

    st.subheader("Antwoord")
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
    elif definition:
        rendered_answer_body = definition
        st.markdown(rendered_answer_body)
    else:
        rendered_answer_body = result.get(
            "answer", "Ik heb geen passende definitie of veldbeschrijving gevonden."
        )
        st.markdown(rendered_answer_body)

    if datasets:
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

    if fields:
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
    try:
        result = answer_definition_question_json(query, debug=debug)
    except Exception as exc:  # noqa: BLE001 - show useful diagnostics during development.
        st.error("Er ging iets mis bij het zoeken in de definitiebestanden.")
        st.exception(exc)
    else:
        render_result(result)
        if debug:
            with st.expander("Debug JSON"):
                st.json(result)
