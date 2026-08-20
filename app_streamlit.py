"""VU EA Conversational AI - chat UI over the local 1cijferHO documentation.

Preferred start (installs dependencies and Ollama models first):
    python main.py

Manual start when the environment is already prepared:
    python -m streamlit run app_streamlit.py

The UI is a thin layer: retrieval, source policy and the optional LLM layer live
in ``src/``. Every answer keeps its sources, so the chat never presents an
unsourced claim as documentation.
"""

from __future__ import annotations

import json
import queue
import threading
import time

import streamlit as st

from src.chatbot import retrieve, stream_llm_answer
from src.conversation import Turn, resolve_followup_query
from src.definitions.corpus import corpus_stats
from src.definitions.search import is_meaningful_llm_inference
from src.definitions.semantic import semantic_status
from src.llm.ollama_client import warm_up
from src.llm.ollama_setup import DEFAULT_BASE_URL, DEFAULT_OLLAMA_MODEL, is_server_running

APP_TITLE = "VU EA Conversational AI"
APP_SUBTITLE = (
    "Vraagbaak voor de 1cijferHO-documentatie van VU Education Analytics - "
    "antwoorden met bronvermelding uit de officiële documentatie."
)

EXAMPLE_QUESTIONS = [
    "Wat is een internationale student?",
    "Wat betekent Indicatie internationale student?",
    "Wat is het verschil tussen opleiding historisch en opleiding actueel?",
    "Welke waarden heeft Indicatie actief op peildatum?",
    "Waar verwijst Opleiding historisch equivalent naar?",
    "Toon alle velden van Inschrijvingen_aggr_UNL_2025.csv",
]

# Answer speed on a laptop without a GPU is dominated by model size.
MODEL_OPTIONS = {
    f"{DEFAULT_OLLAMA_MODEL} — standaard, beste kwaliteit": DEFAULT_OLLAMA_MODEL,
    "qwen3:4b — sneller, iets beknopter": "qwen3:4b",
    "qwen3:1.7b — snelst, voor trage laptops": "qwen3:1.7b",
    "Ander model (zelf invullen)": "",
}

WEB_MODE_OPTIONS = {
    "Uit": "off",
    "Alleen bij ontbrekende lokale context": "fallback",
    "Altijd proberen als extra context": "enhance",
    "Forceer webcontext": "force",
}

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎓",
    layout="wide",
)


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def normalize_text(text: str | None) -> str:
    """Normalize text for simple UI-level intent and duplicate checks."""
    return " ".join(str(text or "").lower().strip().split())


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


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
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


def strip_status_sections(answer: str) -> str:
    """Drop trailing status blocks that the sources panel already shows.

    Deep-context answers end with "Bronstatus:" (and sometimes an
    "LLM-interpretatie:" block). Showing those inline as well as in the sources
    panel makes the chat bubble long and repetitive.
    """
    lines = str(answer or "").splitlines()
    for index, line in enumerate(lines):
        if line.strip() in {"Bronstatus:", "LLM-interpretatie:"}:
            return "\n".join(lines[:index]).rstrip()
    return str(answer or "").rstrip()


def render_answer_body(result: dict) -> str:
    """Render the answer itself and return the rendered text."""
    intent = result.get("intent")
    definition = str(result.get("definition") or "").strip()
    datasets = result.get("datasets") or []

    if is_definition_like_query(result.get("query"), result) and definition:
        return render_definition_answer(result.get("main_term"), definition)
    if intent == "location" and datasets:
        body = f"Je vindt data over {display_topic(result.get('main_term'))} vooral in de volgende bestanden:"
        st.markdown(body)
        render_bullets(datasets, code=True)
        return body
    if definition:
        st.markdown(definition)
        return definition

    body = strip_status_sections(result.get("answer", "")) or (
        "Ik heb geen passende definitie of veldbeschrijving gevonden."
    )
    st.markdown(body)
    return body


def render_semantic_context(result: dict) -> None:
    """Show semantic hits, always labelled as orientation instead of definition."""
    hits = result.get("semantic_context") or []
    if not hits:
        return
    st.subheader("Semantisch gevonden fragmenten")
    st.caption(
        "Deze fragmenten komen uit de lokale officiële documentatie via de semantische "
        "zoeklaag. Ze zijn géén vastgestelde definitie, maar wel de dichtstbijzijnde "
        "brontekst bij je vraag."
    )
    for hit in hits:
        location = hit.get("source_document") or hit.get("term") or "Documentfragment"
        page = f" — p. {hit['page']}" if hit.get("page") else ""
        st.markdown(f"- **{location}**{page} — gelijkenis `{hit.get('score')}`")
        st.caption(str(hit.get("preview", ""))[:500])


def render_web_sources(result: dict) -> None:
    """Render official and external web sources in separate, labelled sections."""
    web_context = result.get("web_context") or []
    official_web = [w for w in web_context if w.get("source_tier") == "official_web"]
    external_web = [w for w in web_context if w.get("source_tier") == "external_web"]

    if official_web:
        st.subheader("Officiële webbronnen")
        for source in official_web:
            st.markdown(
                f"- **{source.get('title')}** — `{source.get('domain')}` — "
                f"{source.get('retrieved_at')} — `{source.get('source_tier')}`"
            )
            st.caption(source.get("url", ""))
            st.markdown("**Relevante passage:**")
            st.write(str(source.get("evidence_excerpt") or source.get("text_excerpt", ""))[:700])

    if external_web:
        st.subheader("Externe webbronnen")
        st.warning("Externe webbronnen zijn lager geprioriteerd dan officiële documentatie.")
        for source in external_web:
            st.markdown(
                f"- **{source.get('title')}** — `{source.get('domain')}` — "
                f"{source.get('retrieved_at')} — `{source.get('source_tier')}`"
            )
            st.caption(source.get("url", ""))
            st.markdown("**Relevante passage:**")
            st.write(str(source.get("evidence_excerpt") or source.get("text_excerpt", ""))[:700])


def render_field_details(result: dict) -> None:
    """Render the field table or the detail card of a single catalog field."""
    if result.get("field_table"):
        st.subheader("Veldenoverzicht")
        st.dataframe(result["field_table"], use_container_width=True)
        st.download_button(
            "Download velden als JSON",
            data=json.dumps(result["field_table"], ensure_ascii=False, indent=2),
            file_name="inschrijvingen_aggr_2025_fields.json",
            mime="application/json",
            key=f"download-{abs(hash(str(result.get('query'))))}",
        )
    if result.get("field_detail"):
        detail = result["field_detail"]
        st.subheader("Veldkaart")
        st.json({key: detail.get(key) for key in [
            "field_number", "field_name", "bron", "type_field", "dataset", "source_document", "source_path",
        ]})
        if detail.get("possible_values"):
            st.subheader("Mogelijke waarden")
            st.table(detail["possible_values"])
        if detail.get("notes"):
            st.subheader("Let op / NB")
            render_bullets(detail["notes"])
        if detail.get("transformations"):
            st.subheader("Bewerkingen / afleidingen")
            render_bullets(detail["transformations"])
        if detail.get("related_fields"):
            st.subheader("Gerelateerde velden")
            render_bullets(detail["related_fields"], code=True)
    elif result.get("fields"):
        st.subheader("Relevante velden")
        render_bullets(result["fields"], code=True)


def render_sources(result: dict, *, show_source_status: bool = True, debug: bool = False) -> None:
    """Render everything that backs the answer: documents, web, status, fields."""
    if result.get("curated_definition_found") is True:
        st.success("✅ Opgeschoonde definitie gevonden")
    elif result.get("matched_fields"):
        st.info(f"Primaire bron gebruikt: {result.get('primary_source_document')}")
    else:
        st.warning(
            "⚠️ Geen opgeschoonde definitie gevonden; antwoord gebaseerd op "
            "documentatiefragmenten."
        )

    if result.get("source_policy") == "no_difference":
        st.caption(
            "Bronfocus maakt voor deze vraag inhoudelijk geen verschil; "
            "voorkeursranking blijft actief waar relevant."
        )
    if result.get("supplemental_sources"):
        st.caption("Aanvullende context uit andere documenten is gebruikt.")

    datasets = result.get("datasets") or []
    if datasets:
        st.subheader("Bestanden")
        render_bullets(datasets, code=True)

    if result.get("matched_fields"):
        st.subheader("Lokale officiële documentatie")
        for field in result["matched_fields"]:
            st.markdown(f"- **{field.get('field_name')}**: {field.get('description')}")
    if result.get("supplemental_context"):
        st.subheader("Aanvullende lokale documentatie")
        for chunk in result["supplemental_context"]:
            st.markdown(f"- `{chunk.get('source_document')}`: {str(chunk.get('text', ''))[:300]}")

    render_semantic_context(result)
    render_web_sources(result)

    if is_meaningful_llm_inference(result.get("llm_inference")):
        st.subheader("LLM-interpretatie")
        st.write(result["llm_inference"].get("text"))
        st.caption(result["llm_inference"].get("disclaimer"))

    if show_source_status:
        st.subheader("Bronstatus")
        render_bullets(result.get("bronstatus") or ["Lokale officiële documentatie gebruikt."])

    rejected_candidates = result.get("rejected_web_candidates") or []
    if rejected_candidates and debug:
        with st.expander("Geprobeerde maar afgekeurde webpagina’s"):
            for candidate in rejected_candidates:
                st.markdown(f"- `{candidate.get('reject_reason')}` — {candidate.get('url')}")

    if result.get("references"):
        st.subheader("Verwijzingen naar andere documentatie")
        render_bullets(result["references"], code=True)
    if result.get("missing_references"):
        st.subheader("Ontbrekende bronnen")
        render_bullets(result["missing_references"], code=True)

    render_field_details(result)

    if result.get("notes"):
        st.subheader("Let op")
        render_bullets(result["notes"])
    if result.get("related_terms"):
        st.subheader("Andere mogelijke relevante begrippen")
        render_bullets(result["related_terms"])

    with st.expander("Ruwe tekstversie"):
        st.markdown(result.get("answer", ""))
    if debug:
        with st.expander("Debug JSON"):
            st.json(result)


def render_result(result: dict, *, show_source_status: bool = True, debug: bool = False) -> None:
    """Render one complete answer: the answer body plus its sources."""
    render_answer_body(result)
    with st.expander("Bronnen en details", expanded=False):
        render_sources(result, show_source_status=show_source_status, debug=debug)


# --------------------------------------------------------------------------- #
# Retrieval (cached per question + settings)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False, max_entries=128)
def cached_retrieval(
    query: str,
    deep_context: bool,
    source_focus: str,
    include_supplemental: bool,
    web_mode: str,
    allow_external_web: bool,
    allow_llm_inference: bool,
    use_semantic: bool,
    debug: bool,
) -> dict:
    """Answer one question, reusing the result while settings stay the same.

    Streamlit re-runs the whole script on every widget interaction; without this
    cache each toggle would re-run retrieval for every message on screen.
    """
    return retrieve(
        query,
        deep_context=deep_context,
        debug=debug,
        source_focus=source_focus,
        include_supplemental=include_supplemental,
        web_mode=web_mode,
        allow_external_web=allow_external_web,
        allow_llm_inference=allow_llm_inference,
        use_semantic=use_semantic,
    )


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def render_sidebar() -> dict:
    """Render all settings and the status panel; return the chosen settings."""
    st.sidebar.title(APP_TITLE)
    st.sidebar.caption("Instellingen")

    web_mode_label = st.sidebar.selectbox("Webcontext-modus", list(WEB_MODE_OPTIONS), index=1)
    settings = {
        "web_mode": WEB_MODE_OPTIONS[web_mode_label],
        "allow_external_web": st.sidebar.checkbox("Gebruik overige externe webbronnen", value=False),
        "allow_llm_inference": st.sidebar.checkbox("Sta LLM-interpretatie toe", value=True),
        "show_source_status": st.sidebar.checkbox("Toon bronstatus", value=True),
        "use_semantic": st.sidebar.checkbox("Gebruik semantische zoeklaag", value=True),
        "use_llm": st.sidebar.checkbox("Gebruik LLM-formuleerlaag", value=False),
    }
    model_label = st.sidebar.selectbox(
        "Ollama-model",
        list(MODEL_OPTIONS),
        index=0,
        help="Kleiner model = sneller antwoord. Op een laptop zonder GPU scheelt dat veel.",
        disabled=not settings["use_llm"],
    )
    settings["model"] = MODEL_OPTIONS[model_label] or st.sidebar.text_input(
        "Modelnaam", value=DEFAULT_OLLAMA_MODEL, disabled=not settings["use_llm"]
    )
    settings["deep_context"] = st.sidebar.checkbox("Gebruik deep-context antwoorden", value=True)
    settings["focus_primary"] = st.sidebar.checkbox(
        "Focus op Aggregaatbestand inschrijvingen_1cHO2025.docx", value=True
    )
    settings["include_supplemental"] = st.sidebar.checkbox(
        "Volg verwijzingen naar aanvullende documentatie", value=True
    )
    settings["debug"] = st.sidebar.checkbox("Toon debug-informatie", value=False)

    ollama_online = is_server_running(DEFAULT_BASE_URL)
    if settings["use_llm"] and not ollama_online:
        st.sidebar.warning(
            f"Ollama lijkt niet te draaien op {DEFAULT_BASE_URL}. "
            "Start de app met `python main.py` of draai `ollama serve`."
        )
    if settings["use_llm"] and ollama_online:
        ensure_model_loaded(settings["model"])

    with st.sidebar.expander("Status", expanded=False):
        stats = corpus_stats()
        st.markdown(
            f"- Kennisbank: **{sum(stats.values())}** fragmenten "
            f"({stats.get('curated', 0)} definities, {stats.get('index', 0)} indexrijen, "
            f"{stats.get('chunk', 0)} documentfragmenten)"
        )
        st.markdown(f"- Ollama: {'🟢 bereikbaar' if ollama_online else '⚪ niet gestart (optioneel)'}")
        status = semantic_status()
        if status.get("available"):
            staleness = " — ⚠️ verouderd, herbouw aanbevolen" if status.get("stale") else ""
            st.markdown(
                f"- Semantische index: 🟢 {status['items']} vectoren "
                f"(`{status['model']}`, {status['backend']}){staleness}"
            )
        else:
            st.markdown("- Semantische index: ⚪ niet gebouwd")
            st.caption(status.get("hint", ""))

    if st.sidebar.button("🧹 Nieuw gesprek", use_container_width=True):
        st.session_state.turns = []
        st.rerun()

    return settings


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #
def render_feedback(turn_index: int, question: str, answer: str) -> None:
    """Offer thumbs up/down and store corrections as developer feedback."""
    from scripts.record_feedback import record_interaction_feedback

    key = f"feedback-{turn_index}"
    stored = st.session_state.feedback.get(key)
    if stored == "up":
        st.caption("👍 Bedankt, dit antwoord is genoteerd als goed.")
        return
    if stored == "down":
        st.caption("👎 Correctie opgeslagen in data/evaluation/developer_feedback_overrides.jsonl.")
        return

    columns = st.columns([1, 1, 8])
    if columns[0].button("👍", key=f"{key}-up", help="Dit antwoord klopt"):
        st.session_state.feedback[key] = "up"
        st.rerun()
    if columns[1].button("👎", key=f"{key}-down", help="Dit antwoord klopt niet"):
        st.session_state.feedback[key] = "pending"
        st.rerun()

    if st.session_state.feedback.get(key) == "pending":
        with st.form(f"{key}-form"):
            correction = st.text_area("Wat had het antwoord moeten zijn?", key=f"{key}-text")
            reason = st.text_input("Reden (optioneel)", key=f"{key}-reason")
            if st.form_submit_button("Correctie opslaan"):
                record_interaction_feedback(
                    question=question,
                    wrong_answer=answer,
                    corrected_answer=correction,
                    reason=reason,
                )
                st.session_state.feedback[key] = "down"
                st.rerun()


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
def _seconds(value: float) -> str:
    """Format a duration so short waits do not read as "0s"."""
    return f"{value:.1f}s" if value < 10 else f"{value:.0f}s"


def stream_answer_with_progress(query: str, result: dict, settings: dict) -> str:
    """Stream the LLM answer while showing how long the user has been waiting.

    A local model spends its first seconds loading and reading the prompt, during
    which it produces nothing. Without a visible counter that is indistinguishable
    from a hang, which is exactly how testers experienced it.
    """
    fragments: queue.Queue = queue.Queue()
    placeholder = st.empty()
    # Read session state here: a worker thread has no Streamlit script context and
    # touching st.session_state from it raises instead of returning the history.
    history = list(st.session_state.turns)
    model = settings["model"]

    def produce() -> None:
        try:
            for fragment in stream_llm_answer(query, result, model=model, history=history):
                fragments.put(("chunk", fragment))
        except Exception as exc:  # noqa: BLE001 - reported to the user below.
            fragments.put(("error", exc))
        finally:
            fragments.put(("done", None))

    worker = threading.Thread(target=produce, daemon=True)
    worker.start()

    started = time.perf_counter()
    text = ""
    first_token_after: float | None = None
    error: Exception | None = None

    while True:
        try:
            kind, value = fragments.get(timeout=0.4)
        except queue.Empty:
            if not text:
                placeholder.markdown(
                    f"⏳ Model denkt na… ({time.perf_counter() - started:.0f}s) — "
                    "het eerste antwoord duurt langer omdat het model geladen wordt."
                )
            continue

        if kind == "chunk":
            if first_token_after is None:
                first_token_after = time.perf_counter() - started
            text += value
            placeholder.markdown(text + " ▌")
        elif kind == "error":
            error = value
        else:
            break

    total = time.perf_counter() - started
    if error is not None:
        placeholder.empty()
        raise error
    if not text:
        placeholder.empty()
        return ""

    placeholder.markdown(text)
    st.caption(
        f"Lokaal gegenereerd met `{settings['model']}` — eerste woord na "
        f"{_seconds(first_token_after or total)}, klaar in {_seconds(total)}."
    )
    return text


def ensure_model_loaded(model: str) -> None:
    """Load the model once per session so the first question is not the slowest."""
    if not model or st.session_state.get("warmed_model") == model:
        return
    with st.spinner(f"Model `{model}` laden (eenmalig, kan even duren)…"):
        loaded = warm_up(model, DEFAULT_BASE_URL, timeout=300)
    st.session_state.warmed_model = model if loaded else None
    if not loaded:
        st.warning(
            f"Model `{model}` kon niet geladen worden. Haal het op met `ollama pull {model}` "
            "of kies een ander model in de zijbalk."
        )


def answer_question(question: str, settings: dict) -> dict:
    """Run retrieval for one chat turn, resolving follow-up questions first."""
    effective_query, subject = resolve_followup_query(question, st.session_state.turns)
    result = cached_retrieval(
        effective_query,
        settings["deep_context"],
        "primary" if settings["focus_primary"] else "auto",
        settings["include_supplemental"],
        settings["web_mode"],
        settings["allow_external_web"],
        settings["allow_llm_inference"],
        settings["use_semantic"],
        settings["debug"],
    )
    result = dict(result)
    result["asked_question"] = question
    result["effective_query"] = effective_query
    result["followup_subject"] = subject
    return result


def render_turn(index: int, turn: Turn, settings: dict) -> None:
    """Render one stored question/answer pair as chat messages."""
    with st.chat_message("user"):
        st.markdown(turn.question)
    with st.chat_message("assistant"):
        if turn.payload.get("followup_subject"):
            st.caption(f"Vervolgvraag begrepen als: “{turn.payload['effective_query']}”")
        if turn.payload.get("llm_answer"):
            st.markdown(turn.payload["llm_answer"])
            with st.expander("Bronnen en details", expanded=False):
                render_sources(turn.payload, show_source_status=settings["show_source_status"], debug=settings["debug"])
        else:
            render_result(turn.payload, show_source_status=settings["show_source_status"], debug=settings["debug"])
        render_feedback(index, turn.question, turn.answer)


def handle_new_question(question: str, settings: dict) -> None:
    """Answer a new question and append it to the conversation."""
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Zoeken in de lokale officiële documentatie..."):
            result = answer_question(question, settings)

        if result.get("followup_subject"):
            st.caption(f"Vervolgvraag begrepen als: “{result['effective_query']}”")

        llm_answer = ""
        if settings["use_llm"]:
            try:
                llm_answer = stream_answer_with_progress(result["effective_query"], result, settings)
            except Exception as exc:  # noqa: BLE001 - keep the app usable when Ollama fails.
                st.warning(f"LLM-laag niet beschikbaar: {exc}")
                st.caption("Hieronder staat het antwoord uit de lokale documentatie zonder LLM-formulering.")

        if llm_answer:
            result["llm_answer"] = llm_answer
            with st.expander("Bronnen en details", expanded=False):
                render_sources(result, show_source_status=settings["show_source_status"], debug=settings["debug"])
            answer_text = llm_answer
        else:
            answer_text = render_answer_body(result)
            with st.expander("Bronnen en details", expanded=False):
                render_sources(result, show_source_status=settings["show_source_status"], debug=settings["debug"])

    st.session_state.turns.append(
        Turn(question=question, answer=answer_text, main_term=result.get("main_term"), payload=result)
    )
    st.rerun()


def main() -> None:
    """Render the whole page."""
    if "turns" not in st.session_state:
        st.session_state.turns = []
    if "feedback" not in st.session_state:
        st.session_state.feedback = {}
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    if "warmed_model" not in st.session_state:
        st.session_state.warmed_model = None

    settings = render_sidebar()

    st.title(f"🎓 {APP_TITLE}")
    st.caption(APP_SUBTITLE)

    if not st.session_state.turns:
        st.markdown("**Voorbeeldvragen**")
        columns = st.columns(3)
        for position, question in enumerate(EXAMPLE_QUESTIONS):
            if columns[position % 3].button(question, use_container_width=True, key=f"example-{position}"):
                st.session_state.pending_question = question
                st.rerun()

    for index, turn in enumerate(st.session_state.turns):
        render_turn(index, turn, settings)

    typed = st.chat_input("Stel een vraag over de HO-documentatie…")
    question = typed or st.session_state.pending_question
    if question:
        st.session_state.pending_question = None
        handle_new_question(question, settings)


main()
