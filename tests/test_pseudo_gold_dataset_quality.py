import json, re, unittest
from pathlib import Path

PSEUDO_GOLD = Path("data/evaluation/pseudo_gold_questions.jsonl")
PSEUDO_CANDIDATES = Path("data/evaluation/pseudo_candidate_questions.jsonl")
GOLD_CORE = Path("data/evaluation/gold_core_questions.jsonl")
NOISY_DATASET = re.compile(r"1\. Inleiding|Het bestand|nationaliteit is onbekend|geboorteland is onbekend|Zie bestand|Mogelijke waarden", re.I)
BAD_VALUES = {"oegd", "nnen", "esco"}

class PseudoGoldDatasetQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold=[json.loads(line) for line in PSEUDO_GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
        cls.candidates=[json.loads(line) for line in PSEUDO_CANDIDATES.read_text(encoding="utf-8").splitlines() if line.strip()]
        cls.core=[json.loads(line) for line in GOLD_CORE.read_text(encoding="utf-8").splitlines() if line.strip()]
    def test_pseudo_gold_has_no_uncertain_rows(self):
        self.assertTrue(self.gold)
        self.assertTrue(all(row.get("label_status") == "pseudo_generated" for row in self.gold))
        self.assertTrue(all(not row.get("needs_human_review") for row in self.gold))
    def test_candidates_are_uncertain_review_rows(self):
        self.assertTrue(self.candidates)
        self.assertTrue(all(row.get("label_status") == "pseudo_uncertain" for row in self.candidates))
        self.assertTrue(all(row.get("needs_human_review") is True for row in self.candidates))
        self.assertTrue(all(row.get("extraction_reason") in {"index_row", "chunk", "curated_medium", "curated_enriched"} for row in self.candidates))
    def test_no_bad_main_terms_in_gateable_data(self):
        for row in self.gold + self.core:
            term=str(row.get("expected_main_term", ""))
            self.assertNotEqual(term, "Bronnen")
            self.assertFalse(term.startswith("Mogelijke waarden"), term)
            self.assertNotIn("Geeft aan", term)
            self.assertNotRegex(term, r"-{5,}")
    def test_no_noisy_definition_expectations(self):
        for row in self.gold:
            if row.get("case_type") == "definition":
                text=" ".join(row.get("expected_answer_contains", []))
                self.assertNotIn("Ex1 = k", text)
                self.assertNotIn("Exgf", text)
    def test_no_prose_datasets_or_bad_values_in_generated_files(self):
        for row in self.gold + self.candidates:
            for dataset in row.get("expected_datasets", []):
                self.assertNotRegex(dataset, NOISY_DATASET)
                self.assertLessEqual(len(dataset), 120)
            for expected in row.get("expected_values", []):
                self.assertNotIn(str(expected.get("value", "")).lower(), BAD_VALUES)
                self.assertNotIn(str(expected.get("meaning_contains", "")).lower(), BAD_VALUES)
    def test_source_documents_are_real_documents(self):
        for row in self.gold + self.candidates:
            self.assertNotEqual(row.get("source_documents"), [row.get("expected_main_term")])
            self.assertTrue(row.get("source_documents"), row.get("id"))
            self.assertTrue(all("." in doc for doc in row.get("source_documents", [])), row.get("source_documents"))
    def test_value_and_related_cases_have_expectations(self):
        for row in self.gold + self.candidates:
            if row.get("case_type") == "value_code":
                self.assertTrue(row.get("expected_values"), row.get("id"))
            if row.get("case_type") == "related_terms":
                self.assertTrue(row.get("expected_related_terms"), row.get("id"))
    def test_suspicious_candidates_have_warnings(self):
        suspicious = [row for row in self.candidates if re.search(r"-{5,}|\bRecords\b|\bLay\b|Ten opzichte", row.get("expected_main_term", ""))]
        self.assertTrue(all(row.get("candidate_quality_warnings") for row in suspicious))

if __name__ == "__main__": unittest.main()
