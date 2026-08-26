"""Guard the repair of definitions the extraction cut in the wrong place.

The rule for all of it: cutting is allowed, rewriting is not. Every character
that survives must come from the source, and every cut must be one the source
itself marks - a row of dashes, a "Mogelijke waarden:" heading, the name of
another documented term. A property test at the bottom pins exactly that.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.definitions.curated_cleanup import (
    clean_definition,
    cut_at_next_heading,
    next_term_boundary,
    split_off_values,
    strip_derivation_block,
)

KNOWN = frozenset({
    "Verblijfsjaar type ho binnen ho",
    "Soort inschrijving actuele instelling",
    "Opleiding actueel equivalent",
    "Indicatie internationale student",
})


class HeadingTests(unittest.TestCase):
    """A heading in these documents is text with a row of dashes under it."""

    def test_the_next_section_is_cut_off(self) -> None:
        text = "De definitie zelf. Soort inschrijving actuele instelling ---------- Indicatie die aangeeft."
        self.assertEqual("De definitie zelf.", cut_at_next_heading(text))

    def test_a_definition_without_a_heading_is_untouched(self) -> None:
        text = "Een gewone definitie met een streepje-woord erin, zoals opleiding-instelling."
        self.assertEqual(text, cut_at_next_heading(text))

    def test_a_short_dash_run_is_not_a_heading(self) -> None:
        """Twee streepjes zijn een gedachtestreepje, geen onderstreping."""
        text = "Iets -- en nog iets."
        self.assertEqual(text, cut_at_next_heading(text))


class TermBoundaryTests(unittest.TestCase):
    """Two signals together, because either one alone is wrong."""

    def test_a_capitalised_term_starting_a_sentence_is_a_boundary(self) -> None:
        text = "overige inschrijvingen Verblijfsjaar type ho binnen ho Het aantal keren dat"
        self.assertEqual(len("overige inschrijvingen "), next_term_boundary(text, KNOWN))

    def test_a_term_mentioned_in_lower_case_is_not(self) -> None:
        text = "neveninschrijving binnen het domein opleiding actueel equivalent"
        self.assertIsNone(next_term_boundary(text, KNOWN))

    def test_a_capitalised_term_ending_a_sentence_is_not(self) -> None:
        text = "Deze definitie sluit aan op het veld Indicatie internationale student."
        self.assertIsNone(next_term_boundary(text, KNOWN))

    def test_short_names_are_ignored(self) -> None:
        """"Uitval" is ook een gewoon woord; daar valt niets uit af te leiden."""
        self.assertIsNone(next_term_boundary("Iets Uitval Het volgende", frozenset({"Uitval"})))


class ValueListTests(unittest.TestCase):
    def test_a_code_list_moves_out_of_the_prose(self) -> None:
        text = "Sleutel van het domein. Mogelijke waarden: 1 = hoofdinschrijving 2 = neveninschrijving"
        body, codes = split_off_values(text, KNOWN)
        self.assertEqual("Sleutel van het domein.", body)
        self.assertEqual([{"code": "1", "meaning": "hoofdinschrijving"},
                          {"code": "2", "meaning": "neveninschrijving"}], codes)

    def test_letters_and_placeholders_count_as_codes(self) -> None:
        text = "Mogelijke waarden: [leeg] = onbekend A = aangewezen instelling J = ja"
        _, codes = split_off_values(text, KNOWN)
        self.assertEqual(["[leeg]", "A", "J"], [code["code"] for code in codes])

    def test_a_single_equation_is_a_sentence_not_a_list(self) -> None:
        text = "Uitleg. Mogelijke waarden: 1 = alleen deze ene"
        body, codes = split_off_values(text, KNOWN)
        self.assertEqual(text, body)
        self.assertEqual([], codes)

    def test_the_last_meaning_does_not_swallow_the_next_section(self) -> None:
        text = ("Mogelijke waarden: 1 = hoofdinschrijving "
                "6 = overige inschrijvingen Verblijfsjaar type ho binnen ho Het aantal keren dat")
        _, codes = split_off_values(text, KNOWN)
        self.assertEqual("overige inschrijvingen", codes[-1]["meaning"])


class DerivationBlockTests(unittest.TestCase):
    def test_a_leading_block_of_rules_is_dropped(self) -> None:
        text = "o Als Ex1 = k -> Ex1 = x Exgf = p en Ex[t] = x, k -> Ex[t] = p De velden zijn afgeleid."
        self.assertEqual("De velden zijn afgeleid.", strip_derivation_block(text))

    def test_an_arrow_later_in_a_definition_is_left_alone(self) -> None:
        """Anders zou één pijl in een zin de hele definitie opeten."""
        text = ("Een lange definitie die pas veel later, ergens na honderdtwintig tekens tekst, "
                "iets zegt als a -> b en verder gewoon doorloopt.")
        self.assertEqual(text, strip_derivation_block(text))

    def test_a_block_with_nothing_after_it_is_kept(self) -> None:
        """Weggooien zou het item leeg maken; dan liever de ruwe tekst."""
        text = "o Als Ex1 = k -> Ex1 = x"
        self.assertEqual(text, strip_derivation_block(text))


class RealDataTests(unittest.TestCase):
    """The measured effect on the file this was written for."""

    @classmethod
    def setUpClass(cls) -> None:
        curated = Path("data/ho_definities_curated.json")
        catalog = Path("data/inschrijvingen_aggr_2025_field_catalog.json")
        if not curated.exists() or not catalog.exists():
            raise unittest.SkipTest("kennisbank niet gebouwd")
        cls.curated = json.loads(curated.read_text(encoding="utf-8"))
        fields = json.loads(catalog.read_text(encoding="utf-8"))
        cls.known = frozenset(
            {field["field_name"] for field in fields}
            | {item["term"] for item in cls.curated}
            | {name for item in cls.curated for name in (item.get("related_fields") or [])}
        )

    def test_nothing_is_rewritten_only_cut(self) -> None:
        """Every surviving word must still be findable in the source text."""
        for item in self.curated:
            source = " ".join(str(item.get("definition", "")).split())
            body, codes = clean_definition(source, self.known)
            if body:
                self.assertIn(body, source, item["term"])
            for code in codes:
                self.assertIn(code["meaning"], source, f"{item['term']}: {code['code']}")

    def test_the_walls_of_text_are_gone(self) -> None:
        longest = 0
        for item in self.curated:
            body, _ = clean_definition(item.get("definition", ""), self.known)
            longest = max(longest, len(body))
        self.assertLess(longest, 1400, "er staat nog een muur tekst in de begrippen")

    def test_the_sleutel_domein_entries_become_a_definition_plus_a_list(self) -> None:
        item = next(x for x in self.curated if x["term"] == "Sleutel domein actuele opleiding")
        body, codes = clean_definition(item["definition"], self.known)
        self.assertLess(len(body), 400, "de tekst is nog steeds een muur")
        self.assertEqual(14, len(codes))
        self.assertEqual("hoofdinschrijving binnen het domein opleiding actueel equivalent",
                         codes[0]["meaning"])
        self.assertNotIn("Soort inschrijving actuele instelling", body)

    def test_a_definition_that_is_only_a_code_list_keeps_the_list(self) -> None:
        item = next(x for x in self.curated if x["term"] == "EER-student")
        body, codes = clean_definition(item["definition"], self.known)
        self.assertEqual("", body)
        self.assertEqual(["J", "N"], [code["code"] for code in codes])

    def test_the_clean_definitions_are_left_exactly_as_they_were(self) -> None:
        """The 23 hand-seeded terms had nothing wrong with them."""
        for item in self.curated:
            if item.get("confidence", 0) < 0.99:
                continue
            source = " ".join(str(item.get("definition", "")).split())
            body, codes = clean_definition(source, self.known)
            if codes:
                continue  # een codelijst eruit halen is wél een verbetering
            self.assertEqual(source, body, item["term"])


if __name__ == "__main__":
    unittest.main()
