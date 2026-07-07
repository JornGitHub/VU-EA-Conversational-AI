import json, unittest
from pathlib import Path

PSEUDO_GOLD = Path("data/evaluation/pseudo_gold_questions.jsonl")

class PseudoGoldDatasetQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=[json.loads(line) for line in PSEUDO_GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    def test_no_bad_main_terms(self):
        for row in self.rows:
            term=str(row.get("expected_main_term", ""))
            self.assertNotEqual(term, "Bronnen")
            self.assertFalse(term.startswith("Mogelijke waarden"), term)
            self.assertNotIn("Geeft aan", term)
    def test_no_noisy_definition_expectations(self):
        for row in self.rows:
            if row.get("case_type") == "definition":
                text=" ".join(row.get("expected_answer_contains", []))
                self.assertNotIn("Ex1 = k", text)
                self.assertNotIn("Exgf", text)
    def test_source_documents_are_real_documents(self):
        for row in self.rows:
            self.assertNotEqual(row.get("source_documents"), [row.get("expected_main_term")])
            self.assertTrue(row.get("source_documents"), row.get("id"))
            self.assertTrue(all("." in doc for doc in row.get("source_documents", [])), row.get("source_documents"))
    def test_value_and_related_cases_have_expectations(self):
        for row in self.rows:
            if row.get("case_type") == "value_code":
                self.assertTrue(row.get("expected_values"), row.get("id"))
            if row.get("case_type") == "related_terms":
                self.assertTrue(row.get("expected_related_terms"), row.get("id"))

if __name__ == "__main__": unittest.main()
