"""Speed changes must not change answers.

Caching and precomputation are only worth anything if the ranking is provably
identical afterwards. These pin the properties the speed-ups depend on.
"""

from __future__ import annotations

import unittest

from src.definitions import text_utils
from src.definitions.search import (
    catalog_fields,
    field_term_score,
    match_catalog_fields,
    prepared_catalog,
    score_prepared_field,
)
from src.definitions.text_utils import normalize_text, tokenize


class TokenizeContractTests(unittest.TestCase):
    """The cache holds a tuple; callers get a list they may mutate."""

    def test_the_returned_list_is_safe_to_mutate(self) -> None:
        first = tokenize("een twee drie")
        first.append("vier")
        self.assertNotIn("vier", tokenize("een twee drie"), "de cache is beschadigd door een caller")

    def test_each_call_returns_a_separate_list(self) -> None:
        self.assertIsNot(tokenize("een twee"), tokenize("een twee"))

    def test_stopword_removal_is_cached_separately(self) -> None:
        with_stopwords = tokenize("de student", remove_stopwords=False)
        without = tokenize("de student", remove_stopwords=True)
        self.assertNotEqual(with_stopwords, without)
        self.assertEqual(with_stopwords, tokenize("de student", remove_stopwords=False))

    def test_non_string_input_still_works(self) -> None:
        """The cache takes strings; everything else is converted before it."""
        self.assertEqual("42", normalize_text(42))
        self.assertEqual("none", normalize_text(None))
        self.assertEqual(["42"], tokenize(42))

    def test_normalisation_is_unchanged_by_caching(self) -> None:
        cases = {
            "Indicatie  internationale-student!": "indicatie internationale student",
            "  MEERDERE   spaties  ": "meerdere spaties",
            "accenten: café, één": "accenten café één",
            "": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(expected, normalize_text(raw), raw)
            self.assertEqual(expected, normalize_text(raw), "tweede aanroep wijkt af")


class PreparedCatalogTests(unittest.TestCase):
    """Precomputing field forms must score exactly like computing them per query."""

    QUERIES = [
        "Wat is een internationale student?",
        "Wat betekent Opleidingsvorm?",
        "peildatum",
        "Welke waarden heeft Indicatie actief op peildatum?",
        "opleiding historisch equivalent",
        "verblijfsjaar hoger onderwijs",
        "croho onderdeel actuele opleiding",
        "eerstejaars aan deze instelling",
        "",
    ]

    def test_prepared_scoring_equals_per_field_scoring(self) -> None:
        for query in self.QUERIES:
            query_norm = normalize_text(query)
            query_tokens = frozenset(tokenize(query_norm))
            for prepared in prepared_catalog():
                self.assertAlmostEqual(
                    field_term_score(query, prepared.field),
                    score_prepared_field(query_norm, query_tokens, prepared),
                    places=9,
                    msg=f"{query} / {prepared.field.get('field_name')}",
                )

    def test_the_prepared_catalog_covers_every_field(self) -> None:
        self.assertEqual(len(catalog_fields()), len(prepared_catalog()))

    def test_preparation_happens_once(self) -> None:
        self.assertIs(prepared_catalog(), prepared_catalog())

    def test_matching_still_finds_the_obvious_answers(self) -> None:
        cases = {
            "Wat betekent Opleidingsvorm?": "Opleidingsvorm",
            "Welke waarden heeft Indicatie actief op peildatum?": "Indicatie actief op peildatum",
            "geslacht": "Geslacht",
        }
        for query, expected in cases.items():
            names = [field.get("field_name") for field in match_catalog_fields(query)]
            self.assertIn(expected, names, f"{query} -> {names}")

    def test_a_peildatum_field_is_penalised_outside_a_peildatum_question(self) -> None:
        """The branch was rewritten; its behaviour must not have moved."""
        peildatum = next(
            prepared for prepared in prepared_catalog() if "peildatum" in prepared.name
        )
        without = score_prepared_field("geslacht", frozenset(["geslacht"]), peildatum)
        with_it = score_prepared_field("peildatum", frozenset(["peildatum"]), peildatum)
        self.assertLess(without, with_it)
        self.assertLessEqual(without, 0)


class ImportCostTests(unittest.TestCase):
    """Answering a question must not pay for libraries it does not use."""

    def test_answering_does_not_import_the_web_or_document_libraries(self) -> None:
        import subprocess
        import sys

        code = (
            "import sys; import src.chatbot; "
            "print('requests' in sys.modules, 'docx' in sys.modules)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=".")
        self.assertEqual("False False", result.stdout.strip(), result.stdout + result.stderr)

    def test_the_deferred_imports_still_work_when_needed(self) -> None:
        from src.definitions import inschrijvingen_catalog, web_sources

        self.assertTrue(hasattr(web_sources, "fetch_web_candidate"))
        self.assertTrue(hasattr(inschrijvingen_catalog, "build_catalog"))


class CacheSizeTests(unittest.TestCase):
    def test_caches_are_bounded(self) -> None:
        """An unbounded cache on user input is a slow memory leak."""
        for cached in (text_utils._normalize_cached, text_utils._tokenize_cached, text_utils.singularize_token):
            self.assertIsNotNone(cached.cache_info().maxsize, cached)


if __name__ == "__main__":
    unittest.main()
