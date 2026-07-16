import json
import unittest
from pathlib import Path

from src.definitions.search import answer_definition_question_json

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "inschrijvingen_aggr_2025_field_catalog.json"


class InschrijvingenCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        cls.by_name = {entry["field_name"]: entry for entry in cls.catalog}

    def test_all_54_fields_present(self):
        self.assertEqual(len(self.catalog), 54)
        self.assertEqual(self.catalog[-1]["field_name"], "Aantal")

    def test_required_metadata_present(self):
        for entry in self.catalog:
            self.assertTrue(entry["field_number"])
            self.assertTrue(entry["field_name"])
            self.assertEqual(entry["dataset"], "Inschrijvingen_aggr_UNL_2025.csv")
            self.assertTrue(entry["bron"])
            self.assertTrue(entry["type_field"])
            self.assertEqual(entry["source_document"], "Aggregaatbestand inschrijvingen_1cHO2025.docx")

    def test_variant_fields_not_confused(self):
        cases = [
            ("Wat betekent Indicatie internationale student?", "Indicatie internationale student"),
            ("Wat betekent Indicatie internationale student op peildatum 1 oktober?", "Indicatie internationale student op peildatum 1 oktober"),
            ("Wat betekent Nationaliteit 1?", "Nationaliteit 1"),
            ("Wat betekent Nationaliteit 1 op peildatum 1 oktober?", "Nationaliteit 1 op peildatum 1 oktober"),
            ("Wat betekent Indicatie EER actueel?", "Indicatie EER actueel"),
            ("Wat betekent Indicatie EER op peildatum 1 oktober?", "Indicatie EER op peildatum 1 oktober"),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                result = answer_definition_question_json(query)
                self.assertEqual(result["field_detail"]["field_name"], expected)

    def test_aantal_telveld_found(self):
        result = answer_definition_question_json("Wat is Aantal?")
        self.assertEqual(result["field_detail"]["field_name"], "Aantal")
        self.assertIn("telveld", result["field_detail"]["aliases"])

    def test_all_fields_query_returns_54(self):
        result = answer_definition_question_json("Toon alle velden van Inschrijvingen_aggr_UNL_2025.csv")
        self.assertEqual(result["intent"], "all_fields")
        self.assertEqual(len(result["field_table"]), 54)

    def test_primary_dataset_and_source_for_field_questions(self):
        result = answer_definition_question_json("Wat betekent Indicatie internationale student op peildatum 1 oktober?")
        self.assertEqual(result["field_detail"]["dataset"], "Inschrijvingen_aggr_UNL_2025.csv")
        self.assertTrue(result["primary_source_used"])
        self.assertEqual(result["field_detail"]["source_document"], "Aggregaatbestand inschrijvingen_1cHO2025.docx")
        self.assertIn("naturalisatie", result["answer"])


if __name__ == "__main__":
    unittest.main()
