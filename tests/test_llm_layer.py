import json
import unittest
from unittest.mock import patch

from src.chatbot import answer_with_llm
from src.llm.prompt_builder import build_grounded_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_grounded_prompt_contains_query_facts_and_rules(self):
        retrieval_result = {
            "query": "wat is een internationale student?",
            "intent": "definition",
            "answer": "Een student wordt als internationale student beschouwd...",
            "main_term": "Internationale student",
            "definition": "Een student wordt als internationale student beschouwd...",
            "fields": ["Indicatie internationale student"],
            "datasets": ["Inschrijvingen_aggr_UNL_2025.csv"],
            "notes": ["Let op peildatum 1 oktober."],
            "related_terms": [],
            "curated_definition_found": True,
        }
        query = "wat is een internationale student?"

        prompt = build_grounded_prompt(query, retrieval_result)

        # The facts must be present...
        self.assertIn(query, prompt)
        self.assertIn("Internationale student", prompt)
        self.assertIn("Een student wordt als internationale student beschouwd", prompt)
        self.assertIn("Indicatie internationale student", prompt)
        self.assertIn("Inschrijvingen_aggr_UNL_2025.csv", prompt)
        self.assertIn("Let op peildatum 1 oktober.", prompt)
        # ...together with the rules that keep the model from inventing more.
        self.assertIn("verzin geen definities, velden, databestanden", prompt)
        self.assertIn("Gebruik uitsluitend de brongegevens", prompt)
        self.assertIn("niet in de beschikbare documentatie", prompt)

    def test_grounded_prompt_stays_compact(self):
        """The prompt carries the facts once instead of the whole payload.

        A local model pays for every prompt token before it writes a word, so a
        prompt that grows with the payload is what made the LLM layer unusable.
        """
        retrieval_result = {
            "query": "wat is een internationale student?",
            "answer": "Een lang antwoord. " * 200,
            "definition": "Een student zonder Nederlandse nationaliteit.",
            "fields": [f"Veld {index}" for index in range(50)],
            "datasets": [f"bestand_{index}.csv" for index in range(30)],
            "notes": ["Een lange NB. " * 60] * 10,
            "matched_fields": [
                {"field_name": f"Veld {index}", "description": "Beschrijving. " * 200,
                 "possible_values": [{"value": str(number), "meaning": "betekenis"} for number in range(40)],
                 "notes": ["NB. " * 100]}
                for index in range(8)
            ],
            "supplemental_context": [{"source_document": "Doc.docx", "text": "Fragment. " * 300}] * 5,
            "semantic_context": [{"source_document": "Doc.docx", "preview": "Fragment. " * 300}] * 5,
            "web_context": [{"title": "Bron", "evidence_excerpt": "Excerpt. " * 300}] * 5,
        }

        prompt = build_grounded_prompt("wat is een internationale student?", retrieval_result)
        raw_payload = json.dumps(retrieval_result, ensure_ascii=False, indent=2)

        self.assertLess(len(prompt), 7000, "prompt budget exceeded")
        self.assertLess(len(prompt), len(raw_payload) / 5)
        self.assertIn("Regels:", prompt)
        self.assertIn("Antwoord:", prompt)


class ChatbotTests(unittest.TestCase):
    @patch("src.chatbot.generate_with_ollama")
    def test_answer_with_llm_returns_retrieval_and_llm_answer(self, mock_generate):
        mock_generate.return_value = "Dit is een gegrond LLM-antwoord."

        result = answer_with_llm("wat is een internationale student?", model="test-model", debug=True)

        self.assertEqual("wat is een internationale student?", result["query"])
        self.assertEqual("test-model", result["model"])
        self.assertEqual("Dit is een gegrond LLM-antwoord.", result["llm_answer"])
        self.assertIn("retrieval_result", result)
        self.assertIn("prompt", result)
        mock_generate.assert_called_once()

    @patch("src.chatbot.generate_with_ollama")
    def test_answer_with_llm_returns_error_without_crashing(self, mock_generate):
        mock_generate.side_effect = RuntimeError("Ollama niet beschikbaar")

        result = answer_with_llm("wat telt als student?", model="test-model")

        self.assertIsNone(result["llm_answer"])
        self.assertIn("Ollama niet beschikbaar", result["error"])
        self.assertIn("retrieval_result", result)
        self.assertNotIn("prompt", result)


if __name__ == "__main__":
    unittest.main()
