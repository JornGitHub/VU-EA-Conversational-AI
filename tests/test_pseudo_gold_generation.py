import contextlib, io, tempfile, unittest
from pathlib import Path
from scripts.evaluation_utils import read_jsonl, write_jsonl
from scripts.generate_pseudo_gold import generate_case_tiers, generate_cases, main

class PseudoGoldGenerationTests(unittest.TestCase):
    def fixture(self, confidence=0.99):
        return {"term":"Internationale student","definition":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding.","aliases":["internationale studenten"],"fields":["Indicatie internationale student"],"datasets":["1cyferho_2025_v1.0.asc"],"source_documents":["Bestandsbeschrijving_1cyferho_2025_v1.0.txt"],"source_fragments":["Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding."],"confidence":confidence,"tags":["field"],"source_terms":["Indicatie internationale student"]}
    def test_generates_source_backed_gate_case_types(self):
        gold, candidates, stats=generate_case_tiers([self.fixture()], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True})
        types={c["case_type"] for c in gold}
        self.assertIn("definition", types); self.assertIn("alias_canonicalisation", types); self.assertIn("fields", types); self.assertIn("location", types); self.assertIn("datasets", types); self.assertIn("related_terms", types)
        self.assertFalse(candidates)
        self.assertTrue(all(c["source_fragments"] for c in gold))
        self.assertTrue(all(c["confidence"] == "high" and c["label_status"] == "pseudo_generated" for c in gold))
        self.assertTrue(all("last_updated" not in c and "expectation_hash" in c for c in gold))
    def test_stable_ids_and_hashes(self):
        first=generate_cases([self.fixture()], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True})
        second=generate_cases([self.fixture()], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True})
        self.assertEqual([c["id"] for c in first], [c["id"] for c in second])
        self.assertEqual([c["expectation_hash"] for c in first], [c["expectation_hash"] for c in second])
    def test_low_confidence_skipped(self):
        self.assertEqual(generate_cases([self.fixture(confidence=0.1)], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True}), [])
    def test_noisy_medium_entry_is_candidate_and_no_definition_expectation(self):
        row=self.fixture(confidence=0.6); row["definition"]="Ex1 = k Exgf Ex[t+1] Mogelijke waarden"; row["source_fragments"]=[row["definition"]]
        gold, candidates, stats=generate_case_tiers([row], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True})
        self.assertFalse(gold)
        self.assertTrue(candidates)
        self.assertTrue(all(c["label_status"] == "pseudo_uncertain" and c["needs_human_review"] for c in candidates))
        self.assertNotIn("definition", {c["case_type"] for c in candidates})
    def test_bad_terms_rejected_and_index_chunks_used_as_candidates(self):
        bad=self.fixture(); bad["term"]="Mogelijke waarden Her1-Her8"
        index={"term":"Index term","definition":"","fields":["Index field"],"datasets":["index.csv"],"source_documents":["Bestandsbeschrijving_1cyferho_2025_v1.0.txt"],"source_fragments":["Index field in index.csv"],"confidence":0.7}
        chunk={"terms":["Chunk term"],"fields":["Chunk field"],"datasets":["chunk.csv"],"source_document":"DUO-trendrapport-ho-2025.pdf","text":"Chunk field appears in chunk.csv"}
        gold, candidates, stats=generate_case_tiers([bad], [index], [chunk], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True})
        self.assertFalse(gold)
        self.assertNotIn("Mogelijke waarden Her1-Her8", {c["expected_main_term"] for c in candidates})
        self.assertIn("Index term", {c["expected_main_term"] for c in candidates})
        self.assertIn("Chunk term", {c["expected_main_term"] for c in candidates})
        self.assertTrue(all(c["label_status"] == "pseudo_uncertain" for c in candidates))
    def test_value_code_requires_expected_values(self):
        row=self.fixture(); row["source_fragments"]=["4 = onechte neveninschrijving; 2 = echte neveninschrijving"]
        cases=[c for c in generate_cases([row], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit en geen Nederlandse vooropleiding", "fields":["Indicatie internationale student"], "datasets":["1cyferho_2025_v1.0.asc"], "related_terms":["Indicatie internationale student"], "curated_definition_found":True}) if c["case_type"] == "value_code"]
        self.assertTrue(cases)
        self.assertTrue(cases[0]["expected_values"])
    def test_failing_field_case_is_demoted_to_candidate(self):
        row=self.fixture()
        gold, candidates, stats=generate_case_tiers([row], [], [], answer_func=lambda q: {"main_term":"Internationale student", "answer":"Student met geen Nederlandse nationaliteit", "fields":[], "datasets":["1cyferho_2025_v1.0.asc"], "curated_definition_found":True})
        self.assertFalse(any(c["case_type"] == "fields" for c in gold))
        demoted=[c for c in candidates if c["case_type"] == "fields"]
        self.assertTrue(demoted)
        self.assertEqual(demoted[0]["extraction_reason"], "demoted_executable")
        self.assertIn("executable_expectation_failed", demoted[0]["candidate_quality_warnings"])
        self.assertTrue(demoted[0]["needs_human_review"])

    def test_writes_split_tier_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); curated=root/"curated.json"; index=root/"index.jsonl"; chunks=root/"chunks.jsonl"; overrides=root/"overrides.jsonl"
            curated.write_text(__import__('json').dumps([self.fixture()]), encoding="utf-8")
            index.write_text("", encoding="utf-8"); chunks.write_text("", encoding="utf-8")
            write_jsonl(overrides, [{"id":"dev","question":"q","label_status":"developer_corrected"}])
            # main() prints a generation summary; keep it out of the test output.
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--curated", str(curated), "--index", str(index), "--chunks", str(chunks), "--pseudo-gold-output", str(root/"pseudo.jsonl"), "--candidate-output", str(root/"candidates.jsonl"), "--gold-core-output", str(root/"gold.jsonl"), "--overrides", str(overrides)])
            self.assertTrue((root/"pseudo.jsonl").exists())
            self.assertTrue((root/"candidates.jsonl").exists())
            self.assertTrue(any(row["id"] == "dev" for row in read_jsonl(root/"gold.jsonl")))

if __name__ == "__main__": unittest.main()
