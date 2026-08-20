"""Tests for the local semantic layer and its graceful degradation."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.definitions import search, semantic
from src.llm.embeddings import EmbeddingError, embed_text, embed_texts, iter_batches

VOCAB = ["student", "internationaal", "opleiding", "diploma", "peildatum", "nationaliteit"]


def fake_embed(texts, model="fake", base_url="", timeout=0):
    """Deterministic bag-of-words embedding, good enough to rank fixtures."""
    vectors = []
    for text in texts:
        lowered = str(text).lower()
        vector = [float(lowered.count(word)) for word in VOCAB]
        if not any(vector):
            vector = [0.001] * len(VOCAB)
        vectors.append(vector)
    return vectors


class TempIndex:
    """Context manager that redirects the vector store to a temporary folder."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            patch.object(semantic, "SEMANTIC_DIR", root),
            patch.object(semantic, "VECTORS_PATH", root / "vectors.f32"),
            patch.object(semantic, "META_PATH", root / "meta.json"),
        ]
        for item in self._patches:
            item.start()
        semantic.clear_index_cache()
        return root

    def __exit__(self, *exc):
        for item in reversed(self._patches):
            item.stop()
        semantic.clear_index_cache()
        self._tmp.cleanup()
        return False


class EmbeddingClientTests(unittest.TestCase):
    def test_batching_covers_every_item(self) -> None:
        batches = list(iter_batches(["a", "b", "c", "d", "e"], 2))
        self.assertEqual([["a", "b"], ["c", "d"], ["e"]], [list(batch) for batch in batches])

    def test_unreachable_server_raises_embedding_error(self) -> None:
        with self.assertRaises(EmbeddingError):
            embed_texts(["test"], base_url="http://127.0.0.1:1")

    def test_embed_text_uses_the_batch_endpoint(self) -> None:
        with patch("src.llm.embeddings._post_json", return_value={"embeddings": [[0.1, 0.2]]}):
            self.assertEqual([0.1, 0.2], embed_text("wat is een student?"))

    def test_legacy_endpoint_is_used_when_batch_endpoint_fails(self) -> None:
        import urllib.error

        calls = []

        def fake_post(url, payload, timeout):
            calls.append(url)
            if url.endswith("/api/embed"):
                raise urllib.error.HTTPError(url, 404, "not found", {}, None)
            return {"embedding": [1.0, 0.0]}

        with patch("src.llm.embeddings._post_json", side_effect=fake_post):
            self.assertEqual([[1.0, 0.0]], embed_texts(["x"]))
        self.assertTrue(calls[0].endswith("/api/embed"))
        self.assertTrue(calls[-1].endswith("/api/embeddings"))


class SemanticIndexTests(unittest.TestCase):
    def build(self) -> dict:
        with patch("src.definitions.semantic.embed_texts", side_effect=fake_embed):
            return semantic.build_semantic_index(model="fake", batch_size=32)

    def test_build_and_search_returns_relevant_fragments(self) -> None:
        with TempIndex():
            report = self.build()
            self.assertTrue(report["written"])
            self.assertGreater(report["vectors"], 100)

            with patch("src.definitions.semantic.embed_texts", side_effect=fake_embed):
                hits, status = semantic.semantic_search("internationale student nationaliteit", top_k=3, min_score=0.1)

            self.assertEqual("semantic_match", status)
            self.assertTrue(hits)
            self.assertLessEqual(len(hits), 3)
            for hit in hits:
                self.assertEqual("semantic", hit["retrieval"])
                self.assertEqual("official_documentation", hit["source_tier"])
                self.assertLessEqual(hit["score"], 1.0001)

    def test_status_reports_a_built_index(self) -> None:
        with TempIndex():
            self.build()
            status = semantic.semantic_status()
            self.assertTrue(status["available"])
            self.assertEqual("fake", status["model"])
            self.assertFalse(status["stale"])
            self.assertGreater(status["items"], 100)

    def test_status_reports_a_missing_index(self) -> None:
        with TempIndex():
            status = semantic.semantic_status()
            self.assertFalse(status["available"])
            self.assertEqual("no_index", status["reason"])
            self.assertIn("--build-embeddings", status["hint"])

    def test_stale_index_is_detected(self) -> None:
        with TempIndex():
            self.build()
            with patch.object(semantic, "_source_signature", return_value={"other.json": [1.0, 2]}):
                self.assertTrue(semantic.semantic_status()["stale"])

    def test_search_without_index_reports_no_index(self) -> None:
        with TempIndex():
            hits, status = semantic.semantic_search("wat dan ook")
            self.assertEqual([], hits)
            self.assertEqual("no_index", status)

    def test_search_without_embedding_server_reports_unavailable(self) -> None:
        with TempIndex():
            self.build()
            with patch("src.definitions.semantic.embed_texts", side_effect=EmbeddingError("down")):
                hits, status = semantic.semantic_search("internationale student")
            self.assertEqual([], hits)
            self.assertEqual("embedding_unavailable", status)

    def test_vectors_are_normalised(self) -> None:
        with TempIndex():
            self.build()
            index = semantic.load_semantic_index()
            row = list(index.vectors[0]) if index.uses_numpy else list(index.vectors[: index.dim])
            self.assertAlmostEqual(1.0, math.sqrt(sum(value * value for value in row)), places=4)


class SemanticFallbackTests(unittest.TestCase):
    def test_fallback_appends_labelled_fragments_to_a_no_answer(self) -> None:
        payload = {"answer": "Ik heb geen betrouwbare definitie gevonden.", "main_term": None}
        hits = [{"source_document": "Doc.docx", "page": 2, "score": 0.71, "preview": "Een fragment."}]
        with patch.object(search, "semantic_index_exists", return_value=True), patch.object(
            search, "semantic_search", return_value=(hits, "semantic_match")
        ):
            result = search.attach_semantic_fallback(payload, "iets onbekends")

        self.assertEqual("semantic_match", result["semantic_status"])
        self.assertEqual(hits, result["semantic_context"])
        self.assertIn("Semantisch gevonden fragmenten", result["answer"])
        self.assertIn("Doc.docx", result["answer"])
        self.assertIn("Ik heb geen betrouwbare definitie gevonden.", result["answer"])
        self.assertIn("Semantische zoeklaag gebruikt op lokale officiële documentatie.", result["bronstatus"])

    def test_fallback_is_a_no_op_without_an_index(self) -> None:
        payload = {"answer": "geen definitie", "main_term": None}
        with patch.object(search, "semantic_index_exists", return_value=False):
            result = search.attach_semantic_fallback(payload, "iets onbekends")
        self.assertEqual("no_index", result["semantic_status"])
        self.assertEqual([], result["semantic_context"])
        self.assertEqual("geen definitie", result["answer"])

    def test_fallback_can_be_disabled(self) -> None:
        payload = {"answer": "geen definitie", "main_term": None}
        with patch.object(search, "semantic_index_exists", return_value=True) as exists:
            result = search.attach_semantic_fallback(payload, "iets", enabled=False)
        exists.assert_not_called()
        self.assertEqual("disabled", result["semantic_status"])

    def test_lexical_answers_do_not_trigger_the_semantic_layer(self) -> None:
        with patch.object(search, "semantic_search") as semantic_call:
            payload = search.answer_definition_question_json("wat is een internationale student?", web_mode="off")
        semantic_call.assert_not_called()
        self.assertEqual("not_needed", payload["semantic_status"])
        self.assertEqual("Internationale student", payload["main_term"])

    def test_unanswerable_question_consults_the_semantic_layer(self) -> None:
        hits = [{"source_document": "Doc.docx", "page": 1, "score": 0.6, "preview": "Fragment."}]
        with patch.object(search, "semantic_index_exists", return_value=True), patch.object(
            search, "semantic_search", return_value=(hits, "semantic_match")
        ) as semantic_call:
            payload = search.answer_definition_question_json("volstrekt onbekende xyzzy vraag", web_mode="off")
        semantic_call.assert_called_once()
        self.assertEqual(hits, payload["semantic_context"])
        self.assertIn("Semantisch gevonden fragmenten", payload["answer"])


if __name__ == "__main__":
    unittest.main()
