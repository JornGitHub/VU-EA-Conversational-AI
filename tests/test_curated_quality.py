from __future__ import annotations

import unittest

from scripts.build_knowledge_base import merge_existing_curated, protected_seed_definitions
from src.definitions.search import build_answer, score_entry
from src.ingestion.validation import validate_curated_entries


class CuratedQualityTests(unittest.TestCase):
    def valid_entry(self, **overrides):
        entry = {
            "term": "Testterm",
            "definition": "Dit is een volledige betrouwbare definitie met genoeg inhoud voor validatie.",
            "datasets": [],
            "fields": [],
            "source_documents": ["s.txt"],
            "confidence": 0.90,
        }
        entry.update(overrides)
        return entry

    def test_validation_rejects_confidence_below_hard_threshold(self):
        errors = validate_curated_entries([self.valid_entry(confidence=0.89)])
        self.assertTrue(any("confidence below 0.9" in error for error in errors))

    def test_validation_rejects_generic_bad_terms(self):
        for term in ("Bronnen", "Mogelijke waarden", "Mogelijke waarden Her1-Her8"):
            with self.subTest(term=term):
                self.assertTrue(validate_curated_entries([self.valid_entry(term=term)]))

    def test_validation_rejects_table_of_contents_definition(self):
        entry = self.valid_entry(
            definition="3.3.7 Instroom 4.1.1 Studiesucces 5.1.2 Uitval overzicht inhoudsopgave pagina 10."
        )
        errors = validate_curated_entries([entry])
        self.assertTrue(any("curated quality" in error for error in errors))

    def test_protected_core_terms_reject_technical_noise(self):
        for term in ("Instroom", "Studiesucces", "Uitval", "EOI-cohort", "Gediplomeerdencohort"):
            with self.subTest(term=term):
                entry = self.valid_entry(
                    term=term,
                    definition="Ex1 = k en Exgf bepalen Ex[t+1] in technische beslisregels zonder bruikbare definitie.",
                )
                errors = validate_curated_entries([entry])
                self.assertTrue(any("protected core term has corrupted definition" in error for error in errors))

    def test_protected_seed_restores_worse_generated_definition(self):
        bad = self.valid_entry(
            term="EOI-cohort",
            definition="Ex1 = k en Exgf bepalen Ex[t+1] via technische beslisregels.",
            confidence=0.99,
        )
        merged = merge_existing_curated([bad], [], "2026-01-01T00:00:00+00:00")
        eoi = next(entry for entry in merged if entry["term"] == "EOI-cohort")
        self.assertIn("eerstejaars onderwijsinstroom", eoi["definition"])
        self.assertNotIn("Ex1 = k", eoi["definition"])

    def test_plural_international_student_merges_into_canonical_seed(self):
        plural = self.valid_entry(
            term="Internationale studenten",
            definition="Internationale studenten zijn studenten zonder Nederlandse nationaliteit en zonder Nederlandse vooropleiding.",
            confidence=0.99,
        )
        merged = merge_existing_curated([plural], [], "2026-01-01T00:00:00+00:00")
        terms = [entry["term"] for entry in merged]
        self.assertIn("Internationale student", terms)
        self.assertNotIn("Internationale studenten", terms)
        canonical = next(entry for entry in merged if entry["term"] == "Internationale student")
        self.assertIn("Internationale studenten", canonical.get("aliases", []))

    def test_onechte_neveninschrijving_seed_is_valid(self):
        seed = next(
            e
            for e in protected_seed_definitions("2026-01-01T00:00:00+00:00")
            if e["term"] == "Onechte neveninschrijving"
        )
        self.assertEqual([], validate_curated_entries([seed]))
        self.assertGreaterEqual(seed["confidence"], 0.90)
        self.assertIn("andere inschrijving", seed["definition"])

    def test_weak_result_group_returns_no_answer(self):
        entry = self.valid_entry(
            term="Uitval",
            definition="Uitval betekent dat de student niet meer ingeschreven staat in de relevante afbakening.",
            confidence=0.99,
        )
        result = {
            "score": score_entry("wat betekent wettelijk collegegeld (laag)?", entry, "curated"),
            "source": "curated",
            "entry": entry,
        }
        group = {
            "key": "uitval",
            "score": result["score"],
            "best": result,
            "results": [result],
            "fields": [],
            "datasets": [],
            "sources": ["curated"],
            "related_terms": set(),
        }
        answer = build_answer([group], "wat betekent wettelijk collegegeld (laag)?")
        self.assertIn("geen betrouwbare definitie gevonden", answer)
        self.assertNotIn("Uitval betekent", answer)


if __name__ == "__main__":
    unittest.main()
