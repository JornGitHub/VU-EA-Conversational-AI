import unittest
from scripts.generate_pseudo_gold import generate_cases

class PseudoGoldGenerationTests(unittest.TestCase):
    def fixture(self, confidence=0.99):
        return {"term":"Internationale student","definition":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding.","aliases":["internationale studenten"],"fields":["Indicatie internationale student"],"datasets":["1cyferho_2025_v1.0.asc"],"source_documents":["doc.txt"],"source_fragments":["Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding."],"confidence":confidence,"tags":["field"]}
    def test_generates_source_backed_case_types(self):
        cases=generate_cases([self.fixture()])
        types={c["case_type"] for c in cases}
        self.assertIn("definition", types); self.assertIn("alias_canonicalisation", types); self.assertIn("fields", types); self.assertIn("location", types); self.assertIn("datasets", types)
        self.assertTrue(all(c["source_fragments"] for c in cases))
    def test_stable_ids(self):
        self.assertEqual([c["id"] for c in generate_cases([self.fixture()])], [c["id"] for c in generate_cases([self.fixture()])])
    def test_low_confidence_skipped(self):
        self.assertEqual(generate_cases([self.fixture(confidence=0.1)]), [])
    def test_noisy_entry_marked_lower_confidence(self):
        row=self.fixture(); row["source_fragments"]=["1. Inleiding Het bestand"]
        cases=generate_cases([row])
        self.assertTrue(cases)
        self.assertTrue(all(c["confidence"] != "high" for c in cases))

if __name__ == "__main__": unittest.main()
