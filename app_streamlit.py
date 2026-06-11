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

    normalized = " ".join(main_term.strip().lower().split())
    special_cases = {
        "internationale student": "internationale student",
        "student / ingeschrevene": "student/ingeschrevene",
        "student/ingeschrevene": "student/ingeschrevene",
    }
    return special_cases.get(normalized, normalized.replace(" / ", "/"))


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
        st.warning("⚠️ Geen opgeschoonde definitie gevonden; antwoord gebaseerd op documentatiefragmenten.")

    intent = result.get("intent")
    definition = str(result.get("definition") or "").strip()
    datasets = result.get("datasets") or []
    fields = result.get("fields") or []
    notes = result.get("notes") or []
    related_terms = result.get("related_terms") or []

    st.subheader("Antwoord")
    if intent == "definition" and definition:
        topic = format_definition_topic(result.get("main_term"))
        if topic:
            st.markdown(f"**Definitie van {topic}:**")
        else:
            st.markdown("**Definitie:**")
        st.markdown(definition)
    elif intent == "location" and datasets:
        topic = display_topic(result.get("main_term"))
        st.markdown(f"Je vindt data over {topic} vooral in de volgende bestanden:")
        render_bullets(datasets, code=True)
    elif definition:
        st.markdown(definition)
    else:
        st.markdown(result.get("answer", "Ik heb geen passende definitie of veldbeschrijving gevonden."))

    if datasets:
        st.subheader("Bestanden")
        render_bullets(datasets, code=True)

    show_definition_section = bool(definition) and intent != "definition"
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
