"""Guard the synthetic dataset: it must stay synthetic, and stay documented.

The whole value of this data is that nobody can mistake it for the real thing
and that it follows the documentation exactly. Both are easy to break silently.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from src.definitions import mock_data


class GenerationTests(unittest.TestCase):
    def test_columns_match_the_documented_catalog(self) -> None:
        catalog = json.loads(mock_data.CATALOG_PATH.read_text(encoding="utf-8"))
        expected = [field["field_name"] for field in sorted(catalog, key=lambda f: f.get("field_number") or 0)]
        header, _ = mock_data.generate_rows(rows=5)
        self.assertEqual(expected, header)

    def test_generation_is_deterministic(self) -> None:
        """A rebuild must not show up as noise in a diff."""
        first = mock_data.generate_rows(rows=25, seed=7)
        second = mock_data.generate_rows(rows=25, seed=7)
        self.assertEqual(first, second)
        other = mock_data.generate_rows(rows=25, seed=8)
        self.assertNotEqual(first[1], other[1])

    def test_every_coded_value_comes_from_the_documentation(self) -> None:
        header, rows = mock_data.generate_rows(rows=400, seed=11)
        report = mock_data.compare_with_documentation(header, rows)
        self.assertEqual([], report["undocumented_columns"])
        self.assertEqual([], report["undocumented_codes"])
        self.assertTrue(report["ok"])

    def test_identifiers_stay_outside_the_real_code_space(self) -> None:
        """A stray export must be recognisably fake at a glance."""
        header, rows = mock_data.generate_rows(rows=200, seed=3)
        index = header.index("Actuele instelling")
        institutions = {row[index] for row in rows}
        self.assertTrue(institutions)
        for code in institutions:
            self.assertTrue(code.startswith("ZZ"), code)

        index = header.index("Opleiding actueel equivalent")
        programmes = {row[index] for row in rows}
        for code in programmes:
            # Echte CROHO-nummers beginnen met 5, 6 of 7; 9xxxx is ongebruikt.
            self.assertTrue(code.startswith("9"), code)

    def test_documented_ranges_are_expanded_into_real_values(self) -> None:
        header, rows = mock_data.generate_rows(rows=300, seed=5)
        index = header.index("Maand vanaf")
        months = {row[index] for row in rows}
        self.assertTrue(months <= {f"{month:02d}" for month in range(1, 13)}, months)
        self.assertGreater(len(months), 6, "de reeks 01 t/m 12 wordt niet uitgeput")

    def test_aggregate_file_carries_a_count_column(self) -> None:
        header, rows = mock_data.generate_rows(rows=30, seed=2)
        index = header.index("Aantal")
        for row in rows:
            self.assertTrue(row[index].isdigit(), row[index])
            self.assertGreaterEqual(int(row[index]), 1)


class ProfileTests(unittest.TestCase):
    def test_profile_summarises_the_generated_rows(self) -> None:
        header, rows = mock_data.generate_rows(rows=120, seed=13)
        profile = mock_data.build_profile(header, rows)
        self.assertEqual(120, profile["rows"])
        self.assertGreater(profile["sum_of_aantal"], 0)
        self.assertEqual(3, profile["fields"]["Opleidingsvorm"]["distinct_values"])
        self.assertIn("geen echte studentgegevens", profile["notice"])

    def test_profile_is_labelled_as_synthetic(self) -> None:
        self.assertIn("SYNTHETISCH", mock_data.SYNTHETIC_NOTICE.upper())
        self.assertEqual("synthetic_example_data", mock_data.SYNTHETIC_TIER)


class AnswerIntegrationTests(unittest.TestCase):
    def test_examples_are_opt_in_and_never_touch_the_answer(self) -> None:
        """Invented counts must not be able to pass for evidence."""
        from src.chatbot import retrieve

        question = "Wat betekent het veld Opleidingsvorm?"
        plain = retrieve(question, use_semantic=False, web_mode="off")
        with_examples = retrieve(question, use_semantic=False, web_mode="off", include_synthetic_examples=True)

        self.assertNotIn("synthetic_examples", plain)
        self.assertIn("synthetic_examples", with_examples)
        self.assertEqual(plain["answer"], with_examples["answer"])

    def test_examples_carry_their_own_tier(self) -> None:
        if not mock_data.load_profile():
            self.skipTest("synthetische dataset niet gebouwd")
        examples = mock_data.examples_for_fields([{"field_name": "Opleidingsvorm"}])
        self.assertTrue(examples)
        self.assertEqual(mock_data.SYNTHETIC_TIER, examples[0]["source_tier"])
        self.assertEqual({"1", "2", "3"}, {value["value"] for value in examples[0]["values"]})

    def test_unknown_field_yields_nothing_rather_than_guessing(self) -> None:
        self.assertEqual([], mock_data.examples_for_fields([{"field_name": "Bestaat Niet"}]))


class CheckerTests(unittest.TestCase):
    """The checker is what survives once real data arrives."""

    def test_it_flags_a_column_the_documentation_does_not_describe(self) -> None:
        report = mock_data.compare_with_documentation(["Opleidingsvorm", "Verzonnen kolom"], [["1", "x"]])
        self.assertIn("Verzonnen kolom", report["undocumented_columns"])
        self.assertFalse(report["ok"])

    def test_it_flags_a_code_without_a_documented_meaning(self) -> None:
        report = mock_data.compare_with_documentation(["Opleidingsvorm"], [["1"], ["9"]])
        self.assertFalse(report["ok"])
        flagged = {entry["field"]: entry["codes"] for entry in report["undocumented_codes"]}
        self.assertEqual(["9"], flagged["Opleidingsvorm"])

    def test_it_accepts_data_that_matches_the_documentation(self) -> None:
        report = mock_data.compare_with_documentation(["Opleidingsvorm"], [["1"], ["2"], ["3"]])
        self.assertTrue(report["ok"], report)


class WrittenFilesTests(unittest.TestCase):
    def test_written_csv_is_semicolon_separated_and_complete(self) -> None:
        if not mock_data.MOCK_CSV.exists():
            self.skipTest("synthetische dataset niet gebouwd")
        with mock_data.MOCK_CSV.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter=";")
            header = next(reader)
            first = next(reader)
        self.assertEqual(54, len(header))
        self.assertEqual(len(header), len(first))

    def test_the_csv_is_not_committed_but_the_profile_is(self) -> None:
        """825 kB of regenerable noise does not belong in a diff."""
        ignore = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/mock/*.csv", ignore)

    def test_the_folder_explains_what_the_data_is(self) -> None:
        readme = (mock_data.MOCK_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("géén echte data", readme)
        self.assertIn("scripts/generate_mock_data.py", readme)


if __name__ == "__main__":
    unittest.main()
