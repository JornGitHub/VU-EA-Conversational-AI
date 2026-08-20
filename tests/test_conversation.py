"""Tests for follow-up question handling and the streaming LLM layer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.chatbot import build_chat_prompt, retrieve, stream_llm_answer
from src.conversation import Turn, format_history_for_prompt, is_followup_question, resolve_followup_query

HISTORY = [Turn("wat is een internationale student?", "Een student zonder...", "Internationale student")]


class FollowupDetectionTests(unittest.TestCase):
    def test_continuation_openers_are_followups(self) -> None:
        for question in ["en op peildatum?", "En de EER-variant?", "waarom telt die niet mee?", "geef een voorbeeld"]:
            self.assertTrue(is_followup_question(question, HISTORY), question)

    def test_standalone_questions_are_not_followups(self) -> None:
        for question in [
            "wat is uitval?",
            "Wat betekent instroom?",
            "welke waarden heeft Indicatie actief op peildatum?",
            "toon alle velden van Inschrijvingen_aggr_UNL_2025.csv",
        ]:
            self.assertFalse(is_followup_question(question, HISTORY), question)

    def test_backreference_word_in_a_short_question_is_a_followup(self) -> None:
        self.assertTrue(is_followup_question("wat is dat precies?", HISTORY))

    def test_nothing_is_a_followup_without_history(self) -> None:
        self.assertFalse(is_followup_question("en op peildatum?", []))

    def test_history_without_a_subject_does_not_trigger_a_rewrite(self) -> None:
        history = [Turn("iets onbekends", "geen antwoord", None)]
        self.assertEqual(("en dan?", None), resolve_followup_query("en dan?", history))


class FollowupRewriteTests(unittest.TestCase):
    def test_subject_is_appended_after_the_user_wording(self) -> None:
        query, subject = resolve_followup_query("en op peildatum?", HISTORY)
        self.assertEqual("en op peildatum? (Internationale student)", query)
        self.assertEqual("Internationale student", subject)

    def test_question_that_already_names_the_subject_is_left_alone(self) -> None:
        query, subject = resolve_followup_query("en de internationale student op peildatum?", HISTORY)
        self.assertEqual("en de internationale student op peildatum?", query)
        self.assertIsNone(subject)

    def test_standalone_question_is_left_alone(self) -> None:
        self.assertEqual(("wat is uitval?", None), resolve_followup_query("wat is uitval?", HISTORY))

    def test_rewritten_followup_still_retrieves_the_subject(self) -> None:
        query, _ = resolve_followup_query("en op peildatum?", HISTORY)
        payload = retrieve(query, web_mode="off")
        self.assertIn("internationale student", str(payload.get("answer", "")).lower())

    def test_dict_history_is_accepted(self) -> None:
        history = [{"question": "q", "answer": "a", "main_term": "Instroom"}]
        query, subject = resolve_followup_query("en dan?", history)
        self.assertEqual("Instroom", subject)
        self.assertIn("Instroom", query)


class HistoryPromptTests(unittest.TestCase):
    def test_history_block_lists_recent_turns(self) -> None:
        text = format_history_for_prompt(HISTORY)
        self.assertIn("Eerdere vragen in dit gesprek", text)
        self.assertIn("wat is een internationale student?", text)

    def test_history_block_is_empty_without_turns(self) -> None:
        self.assertEqual("", format_history_for_prompt([]))

    def test_chat_prompt_contains_history_and_retrieval(self) -> None:
        prompt = build_chat_prompt("en op peildatum?", {"answer": "x", "query": "y"}, HISTORY)
        self.assertIn("Eerdere vragen in dit gesprek", prompt)
        self.assertIn("Retrieval-output:", prompt)

    def test_chat_prompt_without_history_is_the_plain_grounded_prompt(self) -> None:
        prompt = build_chat_prompt("vraag", {"answer": "x"}, [])
        self.assertNotIn("Eerdere vragen", prompt)


class StreamingTests(unittest.TestCase):
    def fake_response(self, lines):
        response = MagicMock()
        response.__enter__ = lambda _self: response
        response.__exit__ = lambda *_args: False
        response.iter_lines.return_value = lines
        response.raise_for_status.return_value = None
        return response

    def test_fragments_are_streamed_in_order(self) -> None:
        lines = [
            '{"message": {"content": "Een "}, "done": false}',
            '{"message": {"content": "internationale "}, "done": false}',
            '{"message": {"content": "student."}, "done": true}',
        ]
        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.return_value = self.fake_response(lines)
            fragments = list(stream_llm_answer("vraag", {"answer": "x"}))
        self.assertEqual(["Een ", "internationale ", "student."], fragments)

    def test_malformed_lines_are_skipped(self) -> None:
        lines = ["", "not json", '{"message": {"content": "ok"}, "done": true}']
        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.return_value = self.fake_response(lines)
            self.assertEqual(["ok"], list(stream_llm_answer("vraag", {"answer": "x"})))

    def test_connection_failure_raises_a_readable_error(self) -> None:
        import requests

        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.side_effect = requests.exceptions.ConnectionError("refused")
            with self.assertRaises(RuntimeError) as raised:
                list(stream_llm_answer("vraag", {"answer": "x"}))
        self.assertIn("Kan geen verbinding maken met Ollama", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
