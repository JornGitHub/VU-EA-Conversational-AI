"""Tests for the cached corpus and the prepared-entry scoring fast path."""

from __future__ import annotations

import json
import tempfile
import unittest
from difflib import SequenceMatcher
from pathlib import Path

from src.definitions import corpus, search
from src.definitions.text_utils import (
    canonical_aliases_for,
    canonical_preference,
    canonical_term,
    entry_search_text,
    normalize_text,
    tokenize,
)

QUERIES = [
    "wat is een internationale student?",
    "waar vind ik data over internationale studenten?",
    "wat is instroom?",
    "wat is studiesucces?",
    "wat is een EER-student?",
    "wat is een onechte neveninschrijving?",
    "welke waarden heeft Indicatie actief op peildatum?",
    "toon alle velden van Inschrijvingen_aggr_UNL_2025.csv",
    "eer studenten",
    "hoacth.csv",
    "inst",
    "s",
    "xyzzy geen match",
    "",
]


def reference_title_score(query: str, entry: dict) -> float:
    """The original difflib-based title scorer, kept as a test oracle."""
    query_norm = normalize_text(query)
    query_tokens = set(tokenize(query))
    best = 0.0
    for candidate in [entry.get("term", ""), *canonical_aliases_for(entry)]:
        candidate_norm = normalize_text(candidate)
        candidate_tokens = set(tokenize(candidate))
        if not candidate_norm or not candidate_tokens:
            continue
        score = 0.0
        if candidate_norm in query_norm or query_norm in candidate_norm:
            score += 10.0
        score += (len(query_tokens & candidate_tokens) / max(len(candidate_tokens), 1)) * 8.0
        ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
        if ratio >= 0.65:
            score += ratio * 4.0
        best = max(best, score)
    return best


def reference_score(query: str, entry: dict, source: str) -> float:
    """The original entry scorer, kept as a test oracle."""
    haystack = normalize_text(entry_search_text(entry))
    term_tokens = set(tokenize(canonical_term(entry.get("term", ""))))
    title_score = reference_title_score(query, entry)
    token_score = 0.0
    for token in tokenize(query):
        if token in haystack:
            token_score += 1.5 if source == "curated" else 1.0
        if token in term_tokens:
            token_score += 3.0 if source == "curated" else 2.0
    if title_score == 0 and token_score == 0:
        return 0.0
    return (
        search.conceptual_bonus(entry, source)
        + (4.0 * canonical_preference(entry) if source == "curated" else 0.0)
        + title_score
        + token_score
    )


class ScoringEquivalenceTests(unittest.TestCase):
    def test_prepared_scoring_matches_reference_scorer_on_full_corpus(self) -> None:
        for query in QUERIES:
            features = search.query_features(query)
            for source, rows in corpus.prepared_corpus():
                for prepared in rows:
                    expected = reference_score(query, prepared.entry, source)
                    actual = search.score_prepared(features, prepared)
                    self.assertEqual(expected, actual, msg=f"{query!r} / {prepared.entry.get('term')!r}")

    def test_fast_reject_never_skips_a_scoring_entry(self) -> None:
        for query in QUERIES:
            features = search.query_features(query)
            for source, rows in corpus.prepared_corpus():
                for prepared in rows:
                    if search.can_score(features, prepared):
                        continue
                    self.assertEqual(
                        0.0,
                        reference_score(query, prepared.entry, source),
                        msg=f"rejected an entry that scores: {query!r} / {prepared.entry.get('term')!r}",
                    )

    def test_score_entry_wrapper_still_scores_raw_entries(self) -> None:
        entry = {"term": "Internationale student", "definition": "Een student zonder Nederlandse nationaliteit."}
        self.assertEqual(
            reference_score("wat is een internationale student?", entry, "curated"),
            search.score_entry("wat is een internationale student?", entry, "curated"),
        )


class CorpusCacheTests(unittest.TestCase):
    def test_repeated_loads_return_the_same_object(self) -> None:
        first = corpus.load_curated_definitions()
        second = corpus.load_curated_definitions()
        self.assertIs(first, second)

    def test_prepared_entries_are_reused_between_questions(self) -> None:
        first = corpus.prepared_source("curated")
        second = corpus.prepared_source("curated")
        self.assertIs(first, second)

    def test_cache_is_invalidated_when_the_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entries.jsonl"
            path.write_text(json.dumps({"term": "Eerste"}) + "\n", encoding="utf-8")
            self.assertEqual("Eerste", corpus.cached_jsonl(path)[0]["term"])

            path.write_text(json.dumps({"term": "Tweede"}) + "\n", encoding="utf-8")
            # Force a different mtime/size signature on fast filesystems.
            import os

            os.utime(path, (0, 0))
            self.assertEqual("Tweede", corpus.cached_jsonl(path)[0]["term"])

    def test_prepared_for_rebuilds_when_a_new_list_is_passed(self) -> None:
        rows = [{"term": "Alpha"}]
        first = corpus.prepared_for("test-source", rows)
        self.assertIs(first, corpus.prepared_for("test-source", rows))
        self.assertIsNot(first, corpus.prepared_for("test-source", [{"term": "Beta"}]))

    def test_corpus_stats_reports_all_sources(self) -> None:
        stats = corpus.corpus_stats()
        self.assertEqual({"curated", "index", "chunk"}, set(stats))
        self.assertTrue(all(count > 0 for count in stats.values()))


if __name__ == "__main__":
    unittest.main()
