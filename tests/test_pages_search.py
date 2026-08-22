"""Guard the browser-only search page and the data it ships.

This page is the only route that works on a phone with nothing installed, so a
broken export or a stale link is worse here than anywhere else.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

DOCS = Path("docs")
PAGE = DOCS / "zoek.html"
DATA = DOCS / "data" / "definities.json"
PAGE_TEXT = PAGE.read_text(encoding="utf-8")


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        if not DATA.exists():
            self.skipTest("docs/data/definities.json niet gebouwd")
        self.payload = json.loads(DATA.read_text(encoding="utf-8"))

    def test_export_covers_the_documented_fields_and_definitions(self) -> None:
        catalog = json.loads(Path("data/inschrijvingen_aggr_2025_field_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(catalog), self.payload["counts"]["fields"])
        self.assertGreater(self.payload["counts"]["definitions"], 20)

    def test_every_entry_has_a_name_and_a_body(self) -> None:
        for entry in self.payload["entries"]:
            self.assertTrue(entry["name"].strip(), entry)
            self.assertTrue(entry["text"].strip(), entry)
            self.assertIn(entry["kind"], {"field", "definition"})

    def test_code_lists_survive_the_export(self) -> None:
        fields = {entry["name"]: entry for entry in self.payload["entries"] if entry["kind"] == "field"}
        codes = {value["code"]: value["meaning"] for value in fields["Opleidingsvorm"]["codes"]}
        self.assertEqual({"1": "voltijd", "2": "deeltijd", "3": "duaal onderwijs"}, codes)

    def test_no_synthetic_or_micro_data_is_published(self) -> None:
        """Only public documentation may be shipped to a static host."""
        raw = DATA.read_text(encoding="utf-8")
        self.assertNotIn("SYNTHETISCH", raw.upper())
        self.assertNotIn("synthetic_example_data", raw)
        for placeholder in ("ZZ01", "ZZ13", "90001"):
            self.assertNotIn(placeholder, raw, f"synthetische placeholder {placeholder} in de export")

    def test_export_stays_small_enough_for_a_phone(self) -> None:
        self.assertLess(DATA.stat().st_size, 600_000, "export te groot voor een mobiele verbinding")


class PageTests(unittest.TestCase):
    def test_page_is_self_contained(self) -> None:
        self.assertNotIn("<script src=", PAGE_TEXT)
        self.assertNotIn('rel="stylesheet"', PAGE_TEXT)

    def test_page_loads_its_data_from_a_relative_path(self) -> None:
        self.assertIn("fetch('data/definities.json')", PAGE_TEXT)

    def test_page_says_what_it_cannot_do(self) -> None:
        """Someone must not think this is the whole app."""
        self.assertIn("taalmodel", PAGE_TEXT)
        self.assertIn("geen studentdata", PAGE_TEXT)

    def test_page_links_back_to_the_full_app(self) -> None:
        self.assertIn('href="./"', PAGE_TEXT)

    def test_search_requires_a_real_signal(self) -> None:
        """Nonsense once matched everything, because definitions scored anyway."""
        self.assertIn("if (!nameHit && inText === 0) { return 0; }", PAGE_TEXT)

    def test_results_are_cut_off_below_a_relevance_floor(self) -> None:
        self.assertIn("var floor = Math.max(NAME_HIT, best * 0.05);", PAGE_TEXT)

    def test_user_text_is_escaped_before_it_is_rendered(self) -> None:
        self.assertIn("function escapeHtml", PAGE_TEXT)
        self.assertIn("escapeHtml(source ||", PAGE_TEXT)
        self.assertIn("escapeHtml(code.code)", PAGE_TEXT)
        self.assertIn("var safe = escapeHtml(text);", PAGE_TEXT)
        # highlight() bouwt HTML; het mag alleen op ge-escapete tekst werken.
        self.assertNotIn("highlight(text, queryTokens) {\n    var safe = text;", PAGE_TEXT)

    def test_start_page_points_at_the_search_page(self) -> None:
        index = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="zoek.html"', index)


if __name__ == "__main__":
    unittest.main()
