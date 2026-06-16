import json
import unittest
from unittest.mock import patch

from src.chatbot import answer_with_llm
from src.llm.prompt_builder import build_grounded_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_grounded_prompt_contains_query_json_and_rules(self):
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

        self.assertIn(query, prompt)
        self.assertIn(json.dumps(retrieval_result, ensure_ascii=False, indent=2), prompt)
        self.assertIn("Verzin geen definities", prompt)
        self.assertIn("Verzin geen velden", prompt)
        self.assertIn("Verzin geen databestanden", prompt)
        self.assertIn("uitsluitend op basis van de retrieval-output", prompt)


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
