"""Guard the browser-only search page and the data it ships.

This page is the only route that works on a phone with nothing installed, so a
broken export or a stale link is worse here than anywhere else.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from scripts.build_pages_data import _answerable

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

    def test_every_entry_has_a_name_and_something_to_show(self) -> None:
        """A few begrippen are nothing but their code list in the source.

        "EER-student" is J = EER-student, N = niet-EER-student and no prose at
        all. That list is the documentation, so the entry is not empty - it just
        has no running text.
        """
        for entry in self.payload["entries"]:
            self.assertTrue(entry["name"].strip(), entry)
            self.assertTrue(entry["text"].strip() or entry.get("codes"), entry)
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

    def test_table_fragments_are_marked_as_unusable_for_answers(self) -> None:
        """The page answers from this export, so a cut-off table must be flagged.

        The source documents contain tables and paragraphs that the text
        extraction split in the wrong place. They stay searchable - the text
        itself is real - but presenting one as a definition would mean building
        an answer out of a fragment.
        """
        flagged = [e for e in self.payload["entries"] if e.get("answerable") is False]
        self.assertTrue(flagged, "geen enkel fragment gemarkeerd; de regel doet niets")
        for entry in flagged:
            self.assertFalse(_answerable(entry["name"], entry["text"]), entry["name"])

    def test_ordinary_definitions_stay_usable(self) -> None:
        by_name = {entry["name"]: entry for entry in self.payload["entries"]}
        for name in ("Internationale student", "Opleidingsvorm", "Verblijfsjaar"):
            self.assertIsNot(by_name[name].get("answerable"), False, name)

    def test_definitions_name_the_document_they_came_from(self) -> None:
        """"1cHO-documentatie" was on every single one, so it said nothing.

        The curated file carries `source_documents`, and the exporter ignored it.
        Where a real filename is known it is now shown; where the source is only
        the term itself, the generic label is the honest answer.
        """
        definitions = [e for e in self.payload["entries"] if e["kind"] == "definition"]
        named = [e for e in definitions if e["source"] != "1cHO-documentatie"]
        self.assertGreaterEqual(len(named), 15, "geen enkele definitie noemt een echt document")
        for entry in named:
            self.assertRegex(entry["source"], r"\.[A-Za-z]{2,5}$", entry["name"])

    def test_no_definition_is_a_wall_of_text_any_more(self) -> None:
        """2400 characters of flattened table is not something anyone reads."""
        for entry in self.payload["entries"]:
            if entry.get("answerable") is False:
                continue  # die zijn dichtgeklapt en als ruwe brontekst gelabeld
            self.assertLess(len(entry["text"]), 900, entry["name"])

    def test_the_code_lists_came_out_of_the_prose(self) -> None:
        by_name = {entry["name"]: entry for entry in self.payload["entries"]}
        sleutel = by_name["Sleutel domein actuele opleiding"]
        self.assertEqual(14, len(sleutel["codes"]))
        self.assertNotIn("Mogelijke waarden:", sleutel["text"])

    def test_a_definition_does_not_run_on_into_the_next_one(self) -> None:
        """It used to end with the whole of the next section."""
        by_name = {entry["name"]: entry for entry in self.payload["entries"]}
        self.assertNotIn("Soort inschrijving actuele instelling",
                         by_name["Sleutel domein actuele opleiding"]["text"])
        self.assertNotIn("Verblijfsjaar hoger onderwijs",
                         by_name["Sleutel domein actuele opleiding-instelling"]["text"])

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

    def test_there_is_a_way_back_to_the_start_page(self) -> None:
        self.assertIn('<a class="backlink" href="./">', PAGE_TEXT)

    def test_the_way_back_is_relative_so_it_follows_the_host(self) -> None:
        """The same file is served from two hosts; hardcoding one breaks the other."""
        self.assertNotIn("github.io", PAGE_TEXT,
                         "een eigen pagina hoort niet via een vaste host aangeroepen te worden")

    def test_the_page_answers_questions_and_not_only_lists_hits(self) -> None:
        self.assertIn("function compose(raw)", PAGE_TEXT)
        self.assertIn("function renderAnswer", PAGE_TEXT)
        self.assertIn('id="answer"', PAGE_TEXT)

    def test_the_page_says_where_its_answers_come_from(self) -> None:
        """Composing from the documentation and generating text are not the same."""
        self.assertIn("Samengesteld op dit toestel", PAGE_TEXT)
        self.assertIn("er is geen taalmodel aan te pas gekomen", PAGE_TEXT)

    def test_the_answer_layer_skips_entries_the_export_marked_unusable(self) -> None:
        self.assertIn("entry.answerable === false", PAGE_TEXT)

    def test_raw_source_text_is_collapsed_and_labelled(self) -> None:
        """Hiding it would be papering over; showing it open would be a lie."""
        self.assertIn("Ruwe brontekst uit het document, geen definitie", PAGE_TEXT)
        self.assertIn("Toon de brontekst (", PAGE_TEXT)

    def test_a_long_code_list_is_collapsed_in_the_result_list(self) -> None:
        self.assertIn("var long = entry.codes.length > 5;", PAGE_TEXT)
        self.assertIn("' mogelijke waarden</summary>'", PAGE_TEXT)

    def test_a_question_is_reduced_to_its_subject_before_searching(self) -> None:
        """Otherwise "wat is een X" never matches the name X exactly."""
        self.assertIn("function subjectOf(raw)", PAGE_TEXT)
        self.assertIn("var subject = subjectOf(raw);", PAGE_TEXT)
        self.assertIn("var query = norm(subject) || norm(raw);", PAGE_TEXT)
        # De losse woorden ook uit het onderwerp, anders trekt "welke waarden
        # heeft X" elk kopje boven een codelijst naar boven.
        self.assertIn("var queryTokens = subjectTokens.length ? subjectTokens : tokens(raw);", PAGE_TEXT)

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


class OfflineTests(unittest.TestCase):
    """A network that blocks device-to-device traffic cannot block this.

    On eduroam the phone never reaches the laptop, so the route that works is
    the one that needs nothing from it. That only holds if the page really is
    installable and really does work without a network.
    """

    def test_the_files_an_offline_app_needs_are_published(self) -> None:
        for name in ("manifest.webmanifest", "sw.js", "icons/icon-192.png", "icons/icon-512.png"):
            self.assertTrue((DOCS / name).exists(), f"docs/{name} ontbreekt")

    def test_the_manifest_is_valid_and_points_at_real_files(self) -> None:
        manifest = json.loads((DOCS / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual("standalone", manifest["display"])
        self.assertIn("zoek.html", manifest["start_url"])
        self.assertTrue(manifest["icons"])
        for icon in manifest["icons"]:
            self.assertTrue((DOCS / icon["src"]).exists(), icon["src"])
        purposes = [icon.get("purpose") for icon in manifest["icons"]]
        self.assertIn("maskable", purposes, "zonder maskable icoon wordt het beginscherm-icoon bijgesneden")

    def test_the_service_worker_caches_everything_the_page_needs(self) -> None:
        worker = (DOCS / "sw.js").read_text(encoding="utf-8")
        for asset in ("./zoek.html", "./data/definities.json"):
            self.assertIn(asset, worker, f"{asset} wordt niet gecachet, dus offline is het weg")

    def test_the_start_page_is_cached_too_so_the_way_back_survives(self) -> None:
        """A back link that only works with a network is the wrong way round."""
        worker = (DOCS / "sw.js").read_text(encoding="utf-8")
        self.assertIn("'./index.html'", worker)
        self.assertIn("'./',", worker, "een navigatie naar de map zelf is een eigen cachesleutel")

    def test_the_service_worker_answers_from_cache_when_the_network_fails(self) -> None:
        worker = (DOCS / "sw.js").read_text(encoding="utf-8")
        self.assertIn("caches.match(request)", worker)
        self.assertIn("return cached", worker, "zonder terugval is offline alsnog stuk")

    def test_old_caches_are_cleaned_up_on_activation(self) -> None:
        """Otherwise a new version leaves the old one to be served forever."""
        worker = (DOCS / "sw.js").read_text(encoding="utf-8")
        self.assertIn("caches.delete", worker)
        self.assertIn("CACHE", worker)

    def test_the_page_registers_the_service_worker(self) -> None:
        self.assertIn("serviceWorker", PAGE_TEXT)
        self.assertIn("register('sw.js')", PAGE_TEXT)

    def test_ios_gets_an_instruction_instead_of_a_button_that_does_nothing(self) -> None:
        """Safari has no beforeinstallprompt; a button there would be a lie."""
        self.assertIn("iPad|iPhone|iPod", PAGE_TEXT)
        self.assertIn("Zet op beginscherm", PAGE_TEXT)
        self.assertIn("install-go').hidden = true", PAGE_TEXT)

    def test_a_dismissed_install_hint_stays_dismissed(self) -> None:
        self.assertIn("vuea-install-dismissed", PAGE_TEXT)

    def test_storage_failures_never_break_the_page(self) -> None:
        """localStorage throws in private mode; the page must not care."""
        uses = [line for line in PAGE_TEXT.splitlines() if "localStorage" in line]
        self.assertTrue(uses, "geen localStorage-gebruik gevonden")
        for line in uses:
            self.assertIn("try {", line, f"onbeschermd gebruik van localStorage: {line.strip()}")
            self.assertIn("catch", line, f"onbeschermd gebruik van localStorage: {line.strip()}")

    def test_related_entries_are_tappable(self) -> None:
        self.assertIn("data-goto", PAGE_TEXT)
        self.assertIn("scrollTo", PAGE_TEXT)

    def test_the_start_page_says_it_works_offline(self) -> None:
        index = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn("offline", index.lower())
        self.assertIn("beginscherm", index)


class AnswerableRuleTests(unittest.TestCase):
    """The rule that decides whether an item may be used as an answer."""

    def test_a_normal_definition_may_be_used(self) -> None:
        self.assertTrue(_answerable("Opleidingsvorm", "Code voor de studievorm waarin de student staat."))

    def test_a_heading_above_a_code_list_is_not_a_term(self) -> None:
        self.assertFalse(_answerable("Mogelijke waarden Her1-Her8", "Inschrijving voor dezelfde opleiding"))
        self.assertFalse(_answerable("Bronnen", "Register Onderwijsresultaten en verder."))

    def test_text_cut_off_mid_sentence_is_not_a_definition(self) -> None:
        self.assertFalse(_answerable("EOI-cohort", "o Als Ex1 = k en Exgf = k -> Exgf = [leeg]"))
        self.assertFalse(_answerable("Masterex5", "masterdiploma behaald heeft in het jaar."))

    def test_a_definition_starting_with_a_number_or_a_placeholder_still_counts(self) -> None:
        self.assertTrue(_answerable("Iets", "1 oktober is de peildatum."))
        self.assertTrue(_answerable("Iets", "[leeg] betekent dat er geen informatie is."))

    def test_an_empty_body_is_never_an_answer(self) -> None:
        self.assertFalse(_answerable("Iets", "   "))


if __name__ == "__main__":
    unittest.main()
