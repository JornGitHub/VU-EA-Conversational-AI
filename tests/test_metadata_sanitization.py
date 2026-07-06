from __future__ import annotations

import unittest

from src.definitions.search import answer_definition_question_json


NOISY_DATASET_PHRASES = [
    "nationaliteit is onbekend",
    "geboorteland is onbekend",
    "1. Inleiding",
    "Het bestand",
    "m 31 augustus",
    "2 of 4 Mogelijke waarden",
    "overige inschrijvingen Verblijfsjaar",
]


class MetadataSanitizationTests(unittest.TestCase):
    def assert_no_noisy_metadata(self, values: list[str], noisy_phrases: list[str] | None = None):
        text = "\n".join(values)
        for phrase in noisy_phrases or NOISY_DATASET_PHRASES:
            self.assertNotIn(phrase, text)

    def test_international_student_metadata_is_clean(self):
        result = answer_definition_question_json("wat is een internationale student?")

        self.assertEqual("Internationale student", result["main_term"])
        self.assertIn("Indicatie internationale student", result["fields"])
        self.assertIn("Indicatie internationale student op peildatum 1 oktober", result["fields"])
        self.assert_no_noisy_metadata(result["fields"], ["Deze indicatie", "NIEUW Deze indicatie"])
        self.assert_no_noisy_metadata(result["datasets"])

    def test_instroom_metadata_does_not_include_international_fragments(self):
        result = answer_definition_question_json("wat is instroom?")

        metadata = result["fields"] + result["datasets"]
        self.assert_no_noisy_metadata(
            metadata,
            [
                "Indicatie internationale student op peildatum 1 oktober (NIEUW) Deze indicatie",
                "Indicatie EER op peildatum 1 oktober Deze indicatie",
                "nationaliteit is onbekend",
            ],
        )
        self.assertNotIn("Indicatie internationale student op peildatum 1 oktober", result["fields"])
        self.assertNotIn("Indicatie EER op peildatum 1 oktober", result["fields"])

    def test_onechte_neveninschrijving_metadata_is_clean(self):
        result = answer_definition_question_json("wat is een onechte neveninschrijving?")

        self.assertIn("Soort inschrijving type ho binnen soort ho", result["fields"])
        self.assertIn("Sleutel domein hoger onderwijs", result["fields"])
        self.assertIn("Sleutel domein actuele opleiding-instelling", result["fields"])
        self.assert_no_noisy_metadata(result["datasets"], ["2 of 4 Mogelijke waarden", "overige inschrijvingen Verblijfsjaar"])

    def test_related_terms_are_canonical_curated_terms_only(self):
        result = answer_definition_question_json("wat is een EER-student?")

        related_text = "\n".join(result["related_terms"])
        self.assertNotIn("Een EER", related_text)
        self.assertNotIn("Geeft aan", related_text)
        self.assertNotIn("Mogelijke waarden", related_text)
        for term in result["related_terms"]:
            self.assertIn(term, {"Internationale student", "Student / ingeschrevene"})


if __name__ == "__main__":
    unittest.main()
