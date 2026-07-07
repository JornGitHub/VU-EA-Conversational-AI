import unittest
from scripts.generate_pseudo_gold import generate_cases

class PseudoGoldGenerationTests(unittest.TestCase):
    def fixture(self, confidence=0.99):
        return {"term":"Internationale student","definition":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding.","aliases":["internationale studenten"],"fields":["Indicatie internationale student"],"datasets":["1cyferho_2025_v1.0.asc"],"source_documents":["Bestandsbeschrijving_1cyferho_2025_v1.0.txt"],"source_fragments":["Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding."],"confidence":confidence,"tags":["field"],"source_terms":["Indicatie internationale student"]}
    def test_generates_source_backed_case_types(self):
        cases=generate_cases([self.fixture()], [], [])
        types={c["case_type"] for c in cases}
        self.assertIn("definition", types); self.assertIn("alias_canonicalisation", types); self.assertIn("fields", types); self.assertIn("location", types); self.assertIn("datasets", types); self.assertIn("related_terms", types)
        self.assertTrue(all(c["source_fragments"] for c in cases))
        self.assertTrue(all(c["confidence"] == "high" for c in cases))
        self.assertTrue(all(c["label_status"] == "pseudo_generated" for c in cases))
        self.assertTrue(all("last_updated" not in c and "expectation_hash" in c for c in cases))
    def test_stable_ids_and_hashes(self):
        first=generate_cases([self.fixture()], [], [])
        second=generate_cases([self.fixture()], [], [])
        self.assertEqual([c["id"] for c in first], [c["id"] for c in second])
        self.assertEqual([c["expectation_hash"] for c in first], [c["expectation_hash"] for c in second])
    def test_low_confidence_skipped(self):
        self.assertEqual(generate_cases([self.fixture(confidence=0.1)], [], []), [])
    def test_noisy_medium_entry_is_uncertain_and_no_definition_expectation(self):
        row=self.fixture(confidence=0.6); row["definition"]="Ex1 = k Exgf Ex[t+1] Mogelijke waarden"; row["source_fragments"]=[row["definition"]]
        cases=generate_cases([row], [], [])
        self.assertTrue(cases)
        self.assertTrue(all(c["label_status"] == "pseudo_uncertain" and c["needs_human_review"] for c in cases))
        self.assertNotIn("definition", {c["case_type"] for c in cases})
    def test_bad_terms_rejected_and_index_chunks_used_as_uncertain(self):
        bad=self.fixture(); bad["term"]="Mogelijke waarden Her1-Her8"
        index={"term":"Index term","definition":"","fields":["Index field"],"datasets":["index.csv"],"source_documents":["Bestandsbeschrijving_1cyferho_2025_v1.0.txt"],"source_fragments":["Index field in index.csv"],"confidence":0.7}
        chunk={"terms":["Chunk term"],"fields":["Chunk field"],"datasets":["chunk.csv"],"source_document":"DUO-trendrapport-ho-2025.pdf","text":"Chunk field appears in chunk.csv"}
        cases=generate_cases([bad], [index], [chunk])
        self.assertNotIn("Mogelijke waarden Her1-Her8", {c["expected_main_term"] for c in cases})
        self.assertIn("Index term", {c["expected_main_term"] for c in cases})
        self.assertIn("Chunk term", {c["expected_main_term"] for c in cases})
        self.assertTrue(all(c["label_status"] == "pseudo_uncertain" for c in cases))
    def test_value_code_requires_expected_values(self):
        row=self.fixture(); row["source_fragments"]=["4 = onechte neveninschrijving; 2 = echte neveninschrijving"]
        cases=[c for c in generate_cases([row], [], []) if c["case_type"] == "value_code"]
        self.assertTrue(cases)
        self.assertTrue(cases[0]["expected_values"])

if __name__ == "__main__": unittest.main()
