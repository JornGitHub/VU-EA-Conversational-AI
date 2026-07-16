import json
import unittest
from pathlib import Path

from src.definitions.search import answer_deep_context_question_json, answer_definition_question_json

ROOT = Path(__file__).resolve().parents[1]


class DeepContextRetrievalTests(unittest.TestCase):
    def test_international_student_definition_keeps_prior_education_nuance(self):
        result = answer_definition_question_json("Wat is een internationale student?")
        answer = result["answer"]
        self.assertIn("geen Nederlandse nationaliteit", answer)
        self.assertIn("geen Nederlandse vooropleiding", answer)
        self.assertIn("voor het HO", answer)

    def test_international_student_field_includes_values_and_nuance(self):
        result = answer_definition_question_json("Wat betekent Indicatie internationale student?")
        answer = result["answer"]
        self.assertEqual(result["field_detail"]["field_name"], "Indicatie internationale student")
        self.assertIn("J = internationale student", answer)
        self.assertIn("N = geen internationale student", answer)
        self.assertIn("voor het HO", answer)

    def test_international_student_current_vs_peildatum_comparison(self):
        result = answer_deep_context_question_json("verschil internationale student actueel en peildatum")
        answer = result["answer"]
        self.assertEqual(result["intent"], "field_comparison")
        self.assertIn("naturalisatie", answer)
        self.assertIn("terugwerkende kracht", answer)
        self.assertIn("vóór naturalisatie", answer)
        self.assertIn("voor het HO", answer)

    def test_opleiding_historisch_actueel_comparison_matches_both_fields_and_references(self):
        result = answer_deep_context_question_json("Wat is het verschil tussen opleiding historisch en opleiding actueel?")
        fields = {field["field_name"] for field in result["matched_fields"]}
        self.assertEqual(result["intent"], "field_comparison")
        self.assertIn("Opleiding actueel equivalent", fields)
        self.assertIn("Opleiding historisch equivalent", fields)
        self.assertNotIn("geen betrouwbare definitie gevonden", result["answer"].lower())
        self.assertIn("hoacth.csv", result["answer"])
        self.assertIn("hoacth_vest.csv", result["answer"])
        self.assertTrue(set(["hoacth.csv", "hoacth_vest.csv"]) <= set(result["missing_references"]))

    def test_opleiding_reference_question(self):
        result = answer_deep_context_question_json("Waar verwijst Opleiding actueel equivalent naar?")
        self.assertEqual(result["intent"], "field_reference")
        self.assertEqual(result["matched_fields"][0]["field_name"], "Opleiding actueel equivalent")
        self.assertIn("hoacth.csv", result["answer"])
        self.assertIn("hoacth_vest.csv", result["answer"])

    def test_deep_context_cases_file_is_exercised(self):
        cases = [json.loads(line) for line in (ROOT / "data/evaluation/deep_context_cases.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            result = answer_deep_context_question_json(case["query"])
            if case.get("expected_intent") == "definition":
                result = answer_definition_question_json(case["query"])
            self.assertEqual(case["expected_intent"], result["intent"])
            blob = json.dumps(result, ensure_ascii=False)
            for text in case.get("must_include", []):
                self.assertIn(text, blob)


if __name__ == "__main__":
    unittest.main()
