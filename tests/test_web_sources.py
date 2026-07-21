from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.definitions.search as search
from src.definitions import web_sources


class WebSourcesTests(unittest.TestCase):
    def test_web_config_defaults_are_free_only(self):
        cfg = web_sources.load_web_config()
        self.assertIs(cfg["allow_paid_apis"], False)
        self.assertIs(cfg["allow_api_key_based_search"], False)
        self.assertEqual(cfg["provider"], "free_only")
        self.assertEqual(cfg["web_mode_default"], "fallback")
        self.assertIs(cfg["external_web_enabled"], False)

    def test_no_required_paid_api_environment_variables(self):
        forbidden = {"BING_API_KEY", "TAVILY_API_KEY", "SERPAPI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY"}
        self.assertFalse(any(name in os.environ and os.environ[name] == "__required__" for name in forbidden))
        provider = web_sources.FreeOnlyProvider()
        self.assertIs(provider.requires_api_key, False)
        self.assertIs(provider.is_paid_or_usage_based, False)

    def test_source_tier_domain_allowlist(self):
        self.assertEqual(web_sources.source_tier_for_url("https://duo.nl/zakelijk"), "official_web")
        self.assertEqual(web_sources.source_tier_for_url("https://example.com/blog"), "external_web")

    def test_external_web_filtered_when_disabled(self):
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False
            def search(self, query, *, allowed_domains=None, max_results=5):
                return [{"title": "External", "url": "https://example.com/a", "snippet": "onechte neveninschrijving"}]
            def fetch(self, url):
                return {"title": "External", "url": url, "snippet": "onechte neveninschrijving", "text": "onechte neveninschrijving uitleg"}
        original_cache = web_sources.CACHE_DIR
        web_sources.CACHE_DIR = web_sources.PROJECT_ROOT / "data" / "web_cache_test"
        try:
            self.assertEqual(web_sources.build_web_context("onechte neveninschrijving", allow_external_web=False, provider=Provider()), [])
        finally:
            web_sources.CACHE_DIR = original_cache

    def test_web_search_not_called_when_fallback_local_context_sufficient(self):
        original = search.build_web_context
        def fail(*args, **kwargs):
            raise AssertionError("web should not be called")
        search.build_web_context = fail
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="fallback")
        finally:
            search.build_web_context = original
        self.assertIs(result["web_attempted"], False)
        self.assertIs(result["web_sources_used"], False)
        self.assertEqual(result["web_decision_reason"], "local_context_sufficient")
        self.assertIn("official_documentation", result["source_tiers_used"])

    def test_web_search_called_when_local_context_insufficient(self):
        original = search.build_web_context
        called = {"value": False}
        def fake(query, **kwargs):
            called["value"] = True
            return [{"source_tier":"official_web","title":"DUO","url":"https://duo.nl/x","domain":"duo.nl","retrieved_at":"2026-07-21T00:00:00+00:00","text_excerpt":"aanvullende context","used_for_answer":True}]
        search.build_web_context = fake
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding actueel equivalent naar?", web_mode="fallback")
        finally:
            search.build_web_context = original
        self.assertIs(called["value"], True)
        self.assertIs(result["web_sources_used"], True)
        self.assertIn("official_web", result["source_tiers_used"])
        self.assertIn("Officiële webbronnen gebruikt.", result["bronstatus"])
        self.assertIsNone(result["llm_inference"])

    def test_conflict_policy_local_documentation_remains_first(self):
        original = search.build_web_context
        search.build_web_context = lambda *a, **k: [{"source_tier":"official_web","title":"new","url":"https://duo.nl/x","domain":"duo.nl","retrieved_at":"2026-07-21T00:00:00+00:00","text_excerpt":"conflicting web claim","used_for_answer":True}]
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding historisch equivalent naar?", web_mode="force")
        finally:
            search.build_web_context = original
        self.assertEqual(result["source_tiers_used"][0], "official_documentation")
        self.assertIn("Officiële webbronnen gebruikt.", result["bronstatus"])
        self.assertIsNone(result["llm_inference"])

    def test_web_mode_off_disables_web(self):
        original = search.build_web_context
        search.build_web_context = lambda *a, **k: (_ for _ in ()).throw(AssertionError("web should not be called"))
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding actueel equivalent naar?", web_mode="off")
        finally:
            search.build_web_context = original
        self.assertEqual(result["web_mode"], "off")
        self.assertIs(result["web_attempted"], False)
        self.assertEqual(result["web_decision_reason"], "web_disabled")

    def test_web_mode_enhance_attempts_without_crashing_when_empty(self):
        original = search.build_web_context
        called = {"value": False}
        def empty(*args, **kwargs):
            called["value"] = True
            return []
        search.build_web_context = empty
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="enhance")
        finally:
            search.build_web_context = original
        self.assertTrue(called["value"])
        self.assertIs(result["web_attempted"], True)
        self.assertIs(result["web_sources_used"], False)
        self.assertEqual(result["web_decision_reason"], "no_free_official_web_context_found")

    def test_web_mode_force_attempts_without_api_keys(self):
        original = search.build_web_context
        search.build_web_context = lambda *a, **k: []
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="force")
        finally:
            search.build_web_context = original
        self.assertIs(result["web_attempted"], True)
        self.assertEqual(result["web_decision_reason"], "no_free_official_web_context_found")


class SourceAwareInterpretationRegressionTests(unittest.TestCase):
    def test_onechte_neveninschrijving_has_contentful_interpretation_and_primary_fields(self):
        result = search.answer_definition_question_json("Wat is een onechte neveninschrijving?")
        answer = result["answer"]
        self.assertIn("wel voorkomt", answer.lower())
        self.assertIn("andere inschrijving", answer)
        self.assertIn("dezelfde student", answer)
        self.assertIn("LLM-interpretatie", answer)
        self.assertTrue("administratief" in answer or "voorzichtig geïnterpreteerd" in answer)
        self.assertIn("Niet bevestigd door interne/mondelinge kennis", answer)
        self.assertNotIn("documentatie en webbronnen", result["llm_inference"]["disclaimer"])
        self.assertFalse(result["web_sources_used"])
        self.assertNotIn("Sleutel domein hoger onderwijs", result["fields"])
        self.assertTrue(all(field.startswith("Soort inschrijving") for field in result["fields"]))

    def test_empty_llm_text_is_not_meaningful(self):
        self.assertFalse(search.is_meaningful_llm_inference({"text": "", "disclaimer": "x"}))
        self.assertFalse(search.is_meaningful_llm_inference(None))

    def test_bronstatus_has_readable_labels_while_json_keeps_tiers(self):
        result = search.answer_definition_question_json("Wat is een onechte neveninschrijving?")
        self.assertIn("official_documentation", result["source_tiers_used"])
        self.assertIn("llm_inference", result["source_tiers_used"])
        self.assertIn("Lokale officiële documentatie gebruikt.", result["bronstatus"])
        self.assertIn("Geen webbronnen gebruikt.", result["bronstatus"])

if __name__ == "__main__":
    unittest.main()
