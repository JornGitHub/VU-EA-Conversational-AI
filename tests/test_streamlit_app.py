"""Guard the app's identity and the parts of the chat UI users depend on."""

from __future__ import annotations

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
        self.assertIn("st.write_stream", APP)
        self.assertIn("stream_llm_answer", APP)
        self.assertIn("record_interaction_feedback", APP)

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
