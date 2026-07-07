from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.definitions.search import answer_definition_question

ROOT = Path(__file__).resolve().parents[1]


class AnswerQualityTests(unittest.TestCase):
    def test_international_student_still_works(self):
        answer = answer_definition_question("wat is een internationale student?")
        self.assertIn("geen Nederlandse nationaliteit", answer)
        self.assertIn("geen Nederlandse vooropleiding", answer)
        self.assertIn("Indicatie internationale student", answer)

    def test_onechte_neveninschrijving(self):
        answer = answer_definition_question("wat is een onechte neveninschrijving?")
        self.assertIn("neveninschrijving", answer.lower())
        self.assertTrue("andere inschrijving" in answer.lower() or "opleiding-instelling" in answer.lower())
        self.assertNotIn("Switch betekent", answer)
        self.assertNotIn("Diploma betekent", answer)

    def test_wettelijk_collegegeld_no_hallucinated_match(self):
        answer = answer_definition_question("wat betekent wettelijk collegegeld (laag)?")
        self.assertIn("geen betrouwbare definitie gevonden", answer)
        self.assertNotIn("de student staat niet meer ingeschreven", answer)
        self.assertNotIn("Switch betekent", answer)
        self.assertNotIn("Doorstuderen betekent", answer)
        self.assertNotIn("Diploma betekent", answer)

    def test_curated_contains_no_obvious_garbage_terms(self):
        curated = json.loads((ROOT / "data" / "ho_definities_curated.json").read_text(encoding="utf-8"))
        terms = {entry.get("term", "") for entry in curated}
        for bad in [
            "Aan de totstandkoming van deze uitgave",
            "Aangezien het niet",
            "Binnen deze groep",
            "De afgelopen drie jaar",
            "Dit",
            "Daarnaast",
        ]:
            self.assertNotIn(bad, terms)
        self.assertLess(len(curated), 250)

    def test_index_and_chunks_still_exist(self):
        index = ROOT / "data" / "ho_definities_index.jsonl"
        chunks = ROOT / "data" / "chunks.jsonl"
        self.assertTrue(index.exists())
        self.assertTrue(chunks.exists())
        self.assertGreater(index.stat().st_size, 0)
        self.assertGreater(chunks.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
