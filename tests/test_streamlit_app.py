"""Guard the app's identity and the parts of the chat UI users depend on."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

APP = Path("app_streamlit.py").read_text(encoding="utf-8")


class AppIdentityTests(unittest.TestCase):
    def test_app_is_named_vu_ea_conversational_ai(self) -> None:
        self.assertIn('APP_TITLE = "VU EA Conversational AI"', APP)
        self.assertIn("page_title=APP_TITLE", APP)

    def test_app_has_a_subtitle_naming_the_documentation_and_owner(self) -> None:
        self.assertIn("APP_SUBTITLE", APP)
        self.assertIn("1cijferHO-documentatie", APP)
        self.assertIn("VU Education Analytics", APP)
        self.assertIn("st.caption(APP_SUBTITLE)", APP)

    def test_old_name_is_gone(self) -> None:
        self.assertNotIn("HO Definitiezoeker", APP)


class ChatSurfaceTests(unittest.TestCase):
    def test_chat_elements_are_present(self) -> None:
        for snippet in ["st.chat_input", "st.chat_message", "st.session_state.turns", "resolve_followup_query"]:
            self.assertIn(snippet, APP)

    def test_answers_are_cached_per_question_and_settings(self) -> None:
        self.assertIn("@st.cache_data", APP)
        self.assertIn("def cached_retrieval", APP)

    def test_streaming_and_feedback_are_wired(self) -> None:
        self.assertIn("stream_answer_with_progress", APP)
        self.assertIn("stream_llm_answer", APP)
        self.assertIn("record_interaction_feedback", APP)

    def test_waiting_for_a_local_model_shows_progress_and_timing(self) -> None:
        self.assertIn("Model denkt na", APP)
        self.assertIn("eerste woord na", APP)

    def test_model_is_warmed_up_and_selectable(self) -> None:
        self.assertIn("def ensure_model_loaded", APP)
        self.assertIn("warm_up", APP)
        self.assertIn("MODEL_OPTIONS", APP)

    def test_worker_thread_does_not_touch_session_state(self) -> None:
        """Streamlit raises when a thread without script context reads session state."""
        worker = APP.split("def produce() -> None:")[1].split("worker = threading.Thread")[0]
        self.assertNotIn("st.session_state", worker)

    def test_semantic_section_is_labelled_as_orientation(self) -> None:
        self.assertIn("Semantisch gevonden fragmenten", APP)
        self.assertIn("géén vastgestelde definitie", APP)

    def test_source_sections_are_still_rendered(self) -> None:
        for section in [
            "Bronnen en details",
            "Bronstatus",
            "Officiële webbronnen",
            "Externe webbronnen",
            "Lokale officiële documentatie",
            "Ontbrekende bronnen",
        ]:
            self.assertIn(section, APP)


if __name__ == "__main__":
    unittest.main()


class SidebarDefaultTests(unittest.TestCase):
    """Everything on by default except debug; the web layer forced.

    These are product decisions a refactor can undo without anyone noticing,
    so they are pinned here rather than left to the widget calls.
    """

    def setUp(self) -> None:
        self.source = Path("app_streamlit.py").read_text(encoding="utf-8")
        start = self.source.index("def render_sidebar()")
        self.sidebar = self.source[start:self.source.index("\ndef ", start + 10)]

    def test_web_context_defaults_to_force(self) -> None:
        self.assertIn('DEFAULT_WEB_MODE = "force"', self.source)
        self.assertIn("index(DEFAULT_WEB_MODE)", self.sidebar)

    def test_every_checkbox_is_on_except_debug(self) -> None:
        checkboxes = re.findall(r'checkbox\(\s*\n?\s*"([^"]+)"[^)]*?value=(True|False|bool\([^)]*\))', self.sidebar, re.S)
        self.assertGreaterEqual(len(checkboxes), 8, checkboxes)
        for label, value in checkboxes:
            if "debug" in label.lower():
                self.assertEqual("False", value, f"{label} hoort uit te staan")
            else:
                self.assertNotEqual("False", value, f"{label} hoort aan te staan")

    def test_the_forced_web_mode_warns_about_its_cost(self) -> None:
        """Forcing the web layer costs seconds per question; say so."""
        self.assertIn("kost per vraag", self.sidebar)


class DataExampleQuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Path("app_streamlit.py").read_text(encoding="utf-8")

    def test_there_are_questions_aimed_at_the_synthetic_data(self) -> None:
        self.assertIn("DATA_EXAMPLE_QUESTIONS", self.source)
        self.assertGreaterEqual(len(self._data_questions()), 4)

    def _data_questions(self) -> list[str]:
        """Read the list from the source; importing the module logs Streamlit noise."""
        block = self.source.split("DATA_EXAMPLE_QUESTIONS = [")[1].split("]")[0]
        return re.findall(r'"([^"]+)"', block)

    def test_each_data_question_actually_produces_examples(self) -> None:
        """A question that shows nothing is worse than no question at all."""
        from src.chatbot import retrieve
        from src.definitions.mock_data import asks_for_a_row, load_profile

        if not load_profile():
            self.skipTest("synthetische dataset niet gebouwd")

        questions = self._data_questions()
        self.assertGreaterEqual(len(questions), 4)
        for question in questions:
            result = retrieve(question, use_semantic=False, web_mode="off", include_synthetic_examples=True)
            produced = bool(result.get("synthetic_examples")) or bool(result.get("synthetic_row"))
            self.assertTrue(produced, f"geen voorbeeldwaarden voor: {question}")
            if asks_for_a_row(question):
                self.assertTrue(result.get("synthetic_row"), question)

    def test_the_data_questions_are_hidden_when_the_dataset_is_off(self) -> None:
        self.assertIn('if settings.get("show_synthetic_examples"):', self.source)

    def test_a_row_question_explains_where_its_answer_is(self) -> None:
        """Retrieval has nothing about record shape, so "not found" misleads."""
        self.assertIn("beschrijft losse velden, niet hoe een rij eruitziet", self.source)
        self.assertIn('expanded=bool(row)', self.source)


class PhoneFallbackTests(unittest.TestCase):
    """When the block is outside the app, offer the route nobody can close."""

    def setUp(self) -> None:
        self.source = Path("app_streamlit.py").read_text(encoding="utf-8")

    def test_the_hotspot_route_is_spelled_out_when_no_fix_applies(self) -> None:
        block = self.source.split('if not result["fixable_here"]:')[1].split("return")[0]
        self.assertIn("hotspot", block.lower())
        self.assertIn("python main.py", block)
        self.assertIn("zoek.html", block, "opzoeken kan zonder netwerkverbinding")

    def test_it_is_not_shown_when_the_app_can_fix_it_itself(self) -> None:
        """Sending someone to a hotspot while a button would do is noise."""
        index_fix = self.source.index('if not result["fixable_here"]:')
        index_button = self.source.index("Firewallregel toevoegen")
        self.assertLess(index_fix, index_button, "de fix-knop hoort na de vroege return te staan")
