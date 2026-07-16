import tempfile, unittest
from pathlib import Path
from scripts.evaluation_utils import load_cases_with_overrides, write_jsonl
from scripts.record_feedback import build_feedback_case, upsert_feedback

class FeedbackOverridesTests(unittest.TestCase):
    def test_append_and_update_by_normalized_question(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"overrides.jsonl"
            row=build_feedback_case({"question":"Wat is X?","corrected_answer":"A"})
            self.assertEqual(len(upsert_feedback(row, path)), 1)
            row2=build_feedback_case({"question":"wat is x","corrected_answer":"B"})
            rows=upsert_feedback(row2, path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["corrected_answer"], "B")
            self.assertEqual(rows[0]["label_status"], "developer_corrected")
    def test_developer_feedback_overrides_pseudo_gold(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pseudo=root/"pseudo.jsonl"; dev=root/"dev.jsonl"
            write_jsonl(pseudo, [{"id":"p","question":"Wat is X?","label_status":"pseudo_generated","expected_main_term":"X"}])
            write_jsonl(dev, [{"id":"d","question":"wat is x","label_status":"developer_corrected","expected_main_term":"Y"}])
            cases=load_cases_with_overrides(pseudo, dev)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["id"], "d")
            self.assertEqual(cases[0]["label_status"], "developer_corrected")

if __name__ == "__main__": unittest.main()
