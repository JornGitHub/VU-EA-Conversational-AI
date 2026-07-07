import tempfile, unittest
from pathlib import Path
from scripts.evaluation_utils import write_jsonl
from scripts.run_evaluation import evaluate_case, run_evaluation

class EvaluationRunnerTests(unittest.TestCase):
    def actual(self):
        return {"main_term":"Internationale student","answer":"geen Nederlandse nationaliteit; geen betrouwbare definitie gevonden","fields":["Indicatie internationale student"],"datasets":["1cyferho_2025_v1.0.asc"],"curated_definition_found":True,"definition":"4 = onechte neveninschrijving","related_terms":["Echte neveninschrijving"]}
    def test_expectation_checks(self):
        case={"expected_main_term":"Internationale student","expected_answer_contains":["geen Nederlandse nationaliteit"],"expected_fields":["Indicatie internationale student"],"expected_datasets":["1cyferho_2025_v1.0.asc"],"forbidden_answer_contains":["Uitval"],"expected_curated_definition_found":True,"expected_values":[{"value":"4","meaning_contains":"onechte neveninschrijving"}],"expected_related_terms":["Echte neveninschrijving"]}
        self.assertEqual(evaluate_case(case, self.actual()), [])
    def test_failures(self):
        case={"expected_main_term":"Uitval","expected_answer_contains":["missing"],"expected_fields":["missing"],"expected_datasets":["missing.csv"],"forbidden_answer_contains":["nationaliteit"],"expected_curated_definition_found":False}
        failures=evaluate_case(case, self.actual())
        for key in ["expected_main_term","expected_answer_contains","expected_fields","expected_datasets","forbidden_answer_contains","expected_curated_definition_found"]:
            self.assertIn(key, failures)
    def test_no_answer_case(self):
        actual={"main_term":None,"answer":"Ik heb geen betrouwbare definitie gevonden","fields":[],"datasets":[],"curated_definition_found":False}
        case={"expected_main_term":None,"expected_answer_contains":["geen betrouwbare definitie gevonden"],"expected_curated_definition_found":False,"forbidden_answer_contains":["Uitval"]}
        self.assertEqual(evaluate_case(case, actual), [])
    def test_developer_corrected_failures_fail_hard(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pseudo=root/"pseudo.jsonl"; overrides=root/"dev.jsonl"
            write_jsonl(pseudo, [{"id":"p1","question":"q","label_status":"pseudo_generated"}])
            write_jsonl(overrides, [{"id":"d1","question":"q","label_status":"developer_corrected","expected_answer_contains":["must"]}])
            code=run_evaluation(pseudo, overrides, root/"results.jsonl", root/"report.md", answer_func=lambda q:{"answer":"no","fields":[],"datasets":[],"curated_definition_found":True,"definition":"4 = onechte neveninschrijving","related_terms":["Echte neveninschrijving"]})
            self.assertEqual(code, 1)

if __name__ == "__main__": unittest.main()
