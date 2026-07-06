from __future__ import annotations

import unittest

from scripts.verify_all import extract_json_object, assert_no_metadata_noise, assert_main_term


class VerifyAllHelperTests(unittest.TestCase):
    def test_extract_json_object_accepts_plain_json(self):
        self.assertEqual({"main_term": "Internationale student"}, extract_json_object('{"main_term": "Internationale student"}'))

    def test_extract_json_object_tolerates_surrounding_text(self):
        stdout = 'debug before\n{"answer": "ok", "main_term": "Internationale student"}\ntrailing text'
        result = extract_json_object(stdout)
        self.assertEqual("Internationale student", result["main_term"])

    def test_metadata_noise_assertion_checks_structured_fields(self):
        with self.assertRaises(SystemExit):
            assert_no_metadata_noise({"query": "q", "datasets": ["hoacth.csv"]}, ["hoacth.csv"])

    def test_main_term_assertion_uses_structured_value(self):
        assert_main_term({"main_term": "Internationale student"}, "Internationale student", "test")
        with self.assertRaises(SystemExit):
            assert_main_term({"main_term": "Internationale studenten"}, "Internationale student", "test")


if __name__ == "__main__":
    unittest.main()
