import tempfile, unittest
from pathlib import Path

from scripts.audit_label_quality import audit_label_quality, validate_label_row
from scripts.evaluation_utils import read_jsonl, write_jsonl

BASE_CASE = {
    "id": "ok",
    "question": "wat is x?",
    "expected_main_term": "Internationale student",
    "expected_answer_contains": ["geen Nederlandse nationaliteit"],
    "expected_datasets": ["1cyferho_2025_v1.0.asc"],
    "expected_fields": [],
    "expected_curated_definition_found": True,
    "source_documents": ["Bestandsbeschrijving_1cyferho_2025_v1.0.txt"],
    "source_fragments": ["bron"],
    "label_status": "pseudo_generated",
    "case_type": "definition",
}

class LabelQualityAuditTests(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(Path("scripts/audit_label_quality.py").exists())
    def test_noisy_terms_are_rejected(self):
        row = dict(BASE_CASE, expected_main_term="Records")
        self.assertIn("noisy_term_generic", {r["rejected_reason"] for r in validate_label_row(row, "gold_core")})
    def test_noisy_answer_snippets_are_rejected(self):
        row = dict(BASE_CASE, expected_answer_contains=["Ex1 = k"])
        self.assertIn("noisy_answer_snippet", {r["rejected_reason"] for r in validate_label_row(row, "gold_core")})
    def test_prose_datasets_are_rejected(self):
        row = dict(BASE_CASE, expected_datasets=["Bestandsbeschrijving x 1. Inleiding Het bestand y.csv"])
        self.assertIn("noisy_dataset_prose", {r["rejected_reason"] for r in validate_label_row(row, "gold_core")})
    def test_missing_real_source_documents_are_rejected(self):
        row = dict(BASE_CASE, source_documents=["Internationale student"])
        self.assertIn("source_document_is_term", {r["rejected_reason"] for r in validate_label_row(row, "gold_core")})
    def test_failing_gold_core_executable_expectation_fails_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_jsonl(root/"gold.jsonl", [BASE_CASE])
            write_jsonl(root/"pseudo.jsonl", [])
            write_jsonl(root/"candidates.jsonl", [])
            code = audit_label_quality(
                gold_core_path=root/"gold.jsonl", pseudo_gold_path=root/"pseudo.jsonl", candidate_path=root/"candidates.jsonl",
                developer_overrides_path=root/"missing_dev.jsonl", developer_corrected_path=root/"missing_corrected.jsonl",
                report_path=root/"report.md", rejected_path=root/"rejected.jsonl",
                answer_func=lambda q: {"main_term":"Wrong", "answer":"", "fields":[], "datasets":[], "curated_definition_found":False},
            )
            self.assertEqual(code, 1)
            self.assertTrue(any(row["rejected_reason"] == "executable_expectation_failed" for row in read_jsonl(root/"rejected.jsonl")))
    def test_candidate_warnings_do_not_fail_audit_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = dict(BASE_CASE, id="cand", label_status="pseudo_uncertain", needs_human_review=True, candidate_quality_warnings=["prose_dataset_fragment"])
            write_jsonl(root/"gold.jsonl", [])
            write_jsonl(root/"pseudo.jsonl", [])
            write_jsonl(root/"candidates.jsonl", [candidate])
            code = audit_label_quality(
                gold_core_path=root/"gold.jsonl", pseudo_gold_path=root/"pseudo.jsonl", candidate_path=root/"candidates.jsonl",
                developer_overrides_path=root/"missing_dev.jsonl", developer_corrected_path=root/"missing_corrected.jsonl",
                report_path=root/"report.md", rejected_path=root/"rejected.jsonl",
                answer_func=lambda q: {},
            )
            self.assertEqual(code, 0)
            self.assertTrue((root/"report.md").exists())
            self.assertTrue((root/"rejected.jsonl").exists())
            self.assertTrue(read_jsonl(root/"rejected.jsonl"))
    def test_audit_function_does_not_print(self):
        """A failing fixture must not print "audit failed" into a passing test run."""
        import contextlib, io
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_jsonl(root/"gold.jsonl", [BASE_CASE])
            write_jsonl(root/"pseudo.jsonl", [])
            write_jsonl(root/"candidates.jsonl", [])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = audit_label_quality(
                    gold_core_path=root/"gold.jsonl", pseudo_gold_path=root/"pseudo.jsonl", candidate_path=root/"candidates.jsonl",
                    developer_overrides_path=root/"missing_dev.jsonl", developer_corrected_path=root/"missing_corrected.jsonl",
                    report_path=root/"report.md", rejected_path=root/"rejected.jsonl",
                    answer_func=lambda q: {"main_term":"Wrong", "answer":"", "fields":[], "datasets":[], "curated_definition_found":False},
                )
        self.assertEqual(code, 1)
        self.assertEqual("", buffer.getvalue())

    def test_cli_main_reports_the_verdict(self):
        import contextlib, io
        from scripts.audit_label_quality import main as audit_main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_jsonl(root/"gold.jsonl", [])
            write_jsonl(root/"pseudo.jsonl", [])
            write_jsonl(root/"candidates.jsonl", [])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = audit_main([
                    "--gold-core", str(root/"gold.jsonl"), "--pseudo-gold", str(root/"pseudo.jsonl"),
                    "--candidates", str(root/"candidates.jsonl"), "--developer-overrides", str(root/"dev.jsonl"),
                    "--developer-corrected", str(root/"corrected.jsonl"), "--report", str(root/"report.md"),
                    "--rejected", str(root/"rejected.jsonl"),
                ])
        self.assertEqual(code, 0)
        self.assertIn("Label quality audit passed", buffer.getvalue())

    def test_verify_all_calls_label_quality_audit(self):
        text = Path("scripts/verify_all.py").read_text(encoding="utf-8")
        self.assertIn("scripts/audit_label_quality.py", text)
        self.assertIn("--dataset", text)
        self.assertIn("gold_core", text)

if __name__ == "__main__": unittest.main()
