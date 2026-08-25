from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

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
        original = search.attempt_web_context
        def fail(*args, **kwargs):
            raise AssertionError("web should not be called")
        search.attempt_web_context = fail
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="fallback")
        finally:
            search.attempt_web_context = original
        self.assertIs(result["web_attempted"], False)
        self.assertIs(result["web_sources_used"], False)
        self.assertEqual(result["web_decision_reason"], "local_context_sufficient")
        self.assertIn("official_documentation", result["source_tiers_used"])

    def test_web_search_called_when_local_context_insufficient(self):
        original = search.attempt_web_context
        called = {"value": False}
        def fake(query, *args, **kwargs):
            called["value"] = True
            context = [{"source_tier":"official_web","title":"DUO","url":"https://duo.nl/x","domain":"duo.nl","retrieved_at":"2026-07-21T00:00:00+00:00","text_excerpt":"aanvullende context","used_for_answer":True}]
            return context, context, [], ["seed_urls"], "relevant_official_web_context_found"
        search.attempt_web_context = fake
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding actueel equivalent naar?", web_mode="fallback")
        finally:
            search.attempt_web_context = original
        self.assertIs(called["value"], True)
        self.assertIs(result["web_sources_used"], True)
        self.assertIn("official_web", result["source_tiers_used"])
        self.assertIn("Officiële webbronnen gebruikt.", result["bronstatus"])
        self.assertIsNone(result["llm_inference"])

    def test_conflict_policy_local_documentation_remains_first(self):
        original = search.attempt_web_context
        search.attempt_web_context = lambda *a, **k: ([{"source_tier":"official_web","title":"new","url":"https://duo.nl/x","domain":"duo.nl","retrieved_at":"2026-07-21T00:00:00+00:00","text_excerpt":"conflicting web claim","used_for_answer":True}], [], [], ["seed_urls"], "relevant_official_web_context_found")
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding historisch equivalent naar?", web_mode="force")
        finally:
            search.attempt_web_context = original
        self.assertEqual(result["source_tiers_used"][0], "official_documentation")
        self.assertIn("Officiële webbronnen gebruikt.", result["bronstatus"])
        self.assertIsNone(result["llm_inference"])

    def test_web_mode_off_disables_web(self):
        original = search.attempt_web_context
        search.attempt_web_context = lambda *a, **k: (_ for _ in ()).throw(AssertionError("web should not be called"))
        try:
            result = search.answer_deep_context_question_json("Waar verwijst Opleiding actueel equivalent naar?", web_mode="off")
        finally:
            search.attempt_web_context = original
        self.assertEqual(result["web_mode"], "off")
        self.assertIs(result["web_attempted"], False)
        self.assertEqual(result["web_decision_reason"], "web_disabled")

    def test_web_mode_enhance_attempts_without_crashing_when_empty(self):
        original = search.attempt_web_context
        called = {"value": False}
        def empty(*args, **kwargs):
            called["value"] = True
            rejected = [{"url":"https://duo.nl/search?q=x","accepted":False,"reject_reason":"search_page"}]
            return [], rejected, rejected, ["seed_urls"], "no_relevant_official_web_context_found"
        search.attempt_web_context = empty
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="enhance")
        finally:
            search.attempt_web_context = original
        self.assertTrue(called["value"])
        self.assertIs(result["web_attempted"], True)
        self.assertIs(result["web_sources_used"], False)
        self.assertEqual(result["web_decision_reason"], "no_relevant_official_web_context_found")

    def test_web_mode_force_attempts_without_api_keys(self):
        original = search.attempt_web_context
        search.attempt_web_context = lambda *a, **k: ([], [{"url":"https://duo.nl/search?q=x","accepted":False,"reject_reason":"search_page"}], [{"url":"https://duo.nl/search?q=x","accepted":False,"reject_reason":"search_page"}], ["seed_urls"], "no_relevant_official_web_context_found")
        try:
            result = search.answer_deep_context_question_json("Wat is het verschil tussen Indicatie internationale student en Indicatie internationale student op peildatum 1 oktober?", web_mode="force")
        finally:
            search.attempt_web_context = original
        self.assertIs(result["web_attempted"], True)
        self.assertEqual(result["web_decision_reason"], "no_relevant_official_web_context_found")

    def test_definition_force_does_not_report_local_context_sufficient(self):
        original = search.attempt_web_context
        search.attempt_web_context = lambda *a, **k: ([], [{"url":"https://duo.nl/search?q=x","accepted":False,"reject_reason":"search_page"}], [{"url":"https://duo.nl/search?q=x","accepted":False,"reject_reason":"search_page"}], ["seed_urls"], "no_relevant_official_web_context_found")
        try:
            result = search.answer_definition_question_json("Wat is een onechte neveninschrijving?", web_mode="force")
        finally:
            search.attempt_web_context = original
        self.assertEqual(result["web_mode"], "force")
        self.assertIs(result["web_attempted"], True)
        self.assertEqual(result["web_decision_reason"], "no_relevant_official_web_context_found")
        self.assertNotIn("Web niet geprobeerd, omdat lokale documentatie voldoende context gaf.", result["bronstatus"])


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

class WebSourceQualityTests(unittest.TestCase):
    def test_404_candidate_rejected(self):
        candidate = web_sources.classify_web_candidate({
            "url": "https://duo.nl/search?q=Wat+is+een+onechte+neveninschrijving",
            "status_code": 404,
            "title": "Pagina 404 - Particulier - DUO Particulier",
            "text": "Pagina niet gevonden Sorry, deze pagina bestaat niet",
        }, "Wat is een onechte neveninschrijving?")
        self.assertFalse(candidate["accepted"])
        self.assertEqual(candidate["reject_reason"], "not_found")

    def test_search_page_rejected(self):
        candidate = web_sources.classify_web_candidate({
            "url": "https://rijksoverheid.nl/search?q=onechte+neveninschrijving",
            "status_code": 200,
            "title": "Zoeken | Rijksoverheid.nl",
            "text": "Zoeken Home Zoek Log in ...",
        }, "onechte neveninschrijving")
        self.assertFalse(candidate["accepted"])
        self.assertEqual(candidate["reject_reason"], "search_page")

    def test_irrelevant_official_page_rejected(self):
        text = "Dit is een lange officiële pagina over totaal andere onderwerpen. " * 20
        candidate = web_sources.classify_web_candidate({
            "url": "https://duo.nl/particulier/diploma.jsp",
            "status_code": 200,
            "title": "Diploma",
            "text": text,
        }, "onechte neveninschrijving")
        self.assertFalse(candidate["accepted"])
        self.assertEqual(candidate["reject_reason"], "not_relevant")

    def test_force_with_only_rejected_candidates_has_no_web_context(self):
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False
            def search(self, query, *, allowed_domains=None, max_results=5):
                return [{"url": "https://duo.nl/search?q=onechte+neveninschrijving", "title": "Zoeken | DUO", "snippet": "Zoeken Home"}]
            def fetch(self, url):
                raise AssertionError("search page should be rejected before fetch")
        result = web_sources.build_web_context_with_candidates("onechte neveninschrijving", provider=Provider())
        self.assertEqual(result["web_context"], [])
        self.assertTrue(any(c["reject_reason"] == "search_page" for c in result["rejected_web_candidates"]))

class WebDiscoveryPipelineTests(unittest.TestCase):
    PDF_URL = "https://duo.nl/zakelijk/images/toelichting-op-de-gegevens-die-duo-levert.pdf"
    PDF_TEXT = (
        "Soort inschrijving ho. Indicatie die de status van de inschrijving in het domein ho aangeeft: "
        "hoofdinschrijving, echte neveninschrijving, onechte neveninschrijving. "
        "Het doel is om dubbeltellingen van de inschrijvingen te voorkomen. "
        "Beslisboom rekenregel hoger onderwijs student."
    )

    def test_seed_url_discovery_adds_duo_pdf(self):
        discovery = web_sources.discover_web_candidates("Wat is een onechte neveninschrijving?")
        urls = [candidate["url"] for candidate in discovery["candidates"]]
        self.assertIn(self.PDF_URL, urls)
        self.assertIn("seed_urls", discovery["strategies"])

    def test_pdf_relevance_accepted(self):
        candidate = web_sources.classify_web_candidate({
            "url": self.PDF_URL,
            "domain": "duo.nl",
            "source_tier": "official_web",
            "status_code": 200,
            "title": "Toelichting op de gegevens die DUO levert",
            "text": self.PDF_TEXT,
            "content_type": "application/pdf",
        }, "Wat is een onechte neveninschrijving?")
        self.assertTrue(candidate["accepted"])
        self.assertEqual(candidate["source_tier"], "official_web")
        self.assertTrue(candidate["used_for_answer"])
        self.assertIn("onechte neveninschrijving", candidate["matched_terms"])
        self.assertGreaterEqual(candidate["relevance_score"], web_sources.RELEVANCE_THRESHOLD)

    def test_search_page_is_discovery_only_not_used_for_answer(self):
        candidate = web_sources.classify_web_candidate({
            "url": "https://duo.nl/search?q=onechte+neveninschrijving",
            "status_code": 200,
            "title": "Zoeken | DUO",
            "text": "Zoeken Home",
            "used_for_answer": False,
        }, "onechte neveninschrijving")
        self.assertFalse(candidate["accepted"])
        self.assertNotEqual(candidate.get("used_for_answer"), True)
        self.assertEqual(candidate["reject_reason"], "search_page")

    def test_force_mode_with_relevant_seed_pdf_uses_web_context(self):
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False
            def search(self, query, *, allowed_domains=None, max_results=5):
                return []
            def fetch(self, url):
                if url == WebDiscoveryPipelineTests.PDF_URL:
                    return {"title": "Toelichting op de gegevens die DUO levert", "url": url, "status_code": 200, "content_type": "application/pdf", "text": WebDiscoveryPipelineTests.PDF_TEXT, "snippet": WebDiscoveryPipelineTests.PDF_TEXT[:200]}
                raise RuntimeError("offline")
        result = web_sources.build_web_context_with_candidates("Wat is een onechte neveninschrijving?", provider=Provider())
        self.assertTrue(result["web_context"])
        self.assertEqual(result["web_context"][0]["url"], self.PDF_URL)
        self.assertTrue(result["web_context"][0]["used_for_answer"])

    def test_fetch_failure_is_rejected_without_crash(self):
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False
            def search(self, query, *, allowed_domains=None, max_results=5):
                return []
            def fetch(self, url):
                raise RuntimeError("offline")
        result = web_sources.build_web_context_with_candidates("Wat is een onechte neveninschrijving?", provider=Provider())
        self.assertEqual(result["web_context"], [])
        self.assertTrue(any(c.get("reject_reason") == "fetch_failed" for c in result["rejected_web_candidates"]))

class WebExcerptAndDisclaimerTests(unittest.TestCase):
    def test_relevant_excerpt_prefers_matched_passage(self):
        intro = "Algemene intro over de Wet register onderwijsdeelnemers. " * 12
        relevant = "Soort inschrijving ho geeft aan of sprake is van een hoofdinschrijving, echte neveninschrijving of onechte neveninschrijving. Deze rekenregel voorkomt dubbeltellingen van inschrijvingen."
        excerpt = web_sources.build_relevant_excerpt(intro + relevant, "Wat is een onechte neveninschrijving?", matched_terms=["onechte neveninschrijving", "Soort inschrijving ho", "dubbeltellingen"])
        self.assertIn("onechte neveninschrijving", excerpt)
        self.assertIn("Soort inschrijving ho", excerpt)
        self.assertIn("dubbeltellingen", excerpt)
        self.assertNotEqual(excerpt[:40], intro[:40])

    def test_disclaimer_mentions_web_only_when_web_context_used(self):
        original = search.attempt_web_context
        context = [{"source_tier":"official_web","title":"Toelichting op de gegevens die DUO levert","url":"https://duo.nl/zakelijk/images/toelichting-op-de-gegevens-die-duo-levert.pdf","domain":"duo.nl","retrieved_at":"2026-07-21T00:00:00+00:00","text_excerpt":"Soort inschrijving ho ... onechte neveninschrijving ... dubbeltellingen","evidence_excerpt":"Soort inschrijving ho ... onechte neveninschrijving ... dubbeltellingen","used_for_answer":True}]
        search.attempt_web_context = lambda *a, **k: (context, context, [], ["seed_urls"], "relevant_official_web_context_found")
        try:
            with_web = search.answer_definition_question_json("Wat is een onechte neveninschrijving?", web_mode="force")
        finally:
            search.attempt_web_context = original
        without_web = search.answer_definition_question_json("Wat is een onechte neveninschrijving?", web_mode="off")
        self.assertIn("lokale officiële documentatie", with_web["llm_inference"]["disclaimer"])
        self.assertIn("officiële webbron", with_web["llm_inference"]["disclaimer"])
        self.assertIn("geen bevestigde interne/mondelinge toelichting", with_web["llm_inference"]["disclaimer"])
        self.assertIn("lokale officiële documentatie", without_web["llm_inference"]["disclaimer"])
        self.assertNotIn("officiële webbron", without_web["llm_inference"]["disclaimer"])
        self.assertEqual(search.build_llm_inference_disclaimer(True), with_web["llm_inference"]["disclaimer"])
        self.assertEqual(search.build_llm_inference_disclaimer(False), without_web["llm_inference"]["disclaimer"])

    def test_llm_prompt_contains_official_web_excerpt(self):
        from src.llm.prompt_builder import build_grounded_prompt
        result = {"official_web_sources": [{"title":"Toelichting op de gegevens die DUO levert", "url":"https://duo.nl/zakelijk/images/toelichting-op-de-gegevens-die-duo-levert.pdf", "evidence_excerpt":"Soort inschrijving ho ... onechte neveninschrijving ... dubbeltellingen"}]}
        prompt = build_grounded_prompt("Wat is een onechte neveninschrijving?", result)
        self.assertIn("Officiële webbronnen:", prompt)
        self.assertIn("Toelichting op de gegevens die DUO levert", prompt)
        self.assertIn("onechte neveninschrijving", prompt)
    def test_interpretation_mentions_duo_context_when_available(self):
        web_context = [{
            "source_tier": "official_web",
            "title": "Toelichting op de gegevens die DUO levert",
            "text_excerpt": "Veldnaam Soort inschrijving ho. Beschrijving: Indicatie die de status van de inschrijving in het domein ho aangeeft, waaronder onechte neveninschrijving. Rekenregel: een beslisboom door DUO.",
            "evidence_excerpt": "Veldnaam Soort inschrijving ho. Beschrijving: Indicatie die de status van de inschrijving in het domein ho aangeeft, waaronder onechte neveninschrijving. Rekenregel: een beslisboom door DUO.",
        }]
        text = search.build_llm_inference_text(
            "Wat is een onechte neveninschrijving?",
            "Een onechte neveninschrijving is een neveninschrijving waarbij de combinatie opleiding-instelling WEL voorkomt bij een andere inschrijving van dezelfde student.",
            web_context=web_context,
        )
        self.assertIn("Soort inschrijving ho", text)
        self.assertIn("status van een inschrijving", text)
        self.assertTrue("rekenregel" in text or "beslisboom" in text)
        self.assertIn("DUO", text)
        self.assertIn("dubbeltellingen", text)

    def test_clean_web_excerpt_removes_table_prefix(self):
        messy = "Kences Nee SK123 Nee Veldnaam Soort inschrijving ho Beschrijving Indicatie die de status van de inschrijving in het domein ho aangeeft (hoofdinschrijving, echte neveninschrijving, inschrijving is niet actief op peildatum 1 oktober, onechte neveninschrijving, opleiding telt niet mee). Afgeleid door DUO IP Ja Rekenregel Een beslisboom o.b.v. veel velden..."
        cleaned = web_sources.clean_web_excerpt(messy)
        self.assertFalse(cleaned.startswith("Kences Nee SK123 Nee"))
        self.assertIn("Veldnaam Soort inschrijving ho", cleaned)
        self.assertIn("onechte neveninschrijving", cleaned)
        self.assertIn("Rekenregel", cleaned)
        self.assertIn("Beschrijving:", cleaned)
        self.assertIn("dubbeltellingen", web_sources.clean_web_excerpt("Veldnaam Soort inschrijving ho Beschrijving tekst. Het doel is om dubbeltellingen van inschrijvingen te voorkomen."))
        self.assertNotIn("dubbel tel", web_sources.clean_web_excerpt("Veldnaam Soort inschrijving ho Beschrijving tekst. Het doel is om dubbeltellingen van inschrijvingen te voorkomen."))


if __name__ == "__main__":
    unittest.main()


class WebFetchPerformanceTests(unittest.TestCase):
    """The answer path used to re-fetch the same pages, one after another.

    Retrieval itself takes about 4 ms; the forced web layer made a question
    take about 4 seconds. These pin the two things that fixed it.
    """

    def setUp(self) -> None:
        import shutil

        shutil.rmtree(web_sources.RAW_CACHE_DIR, ignore_errors=True)
        self.addCleanup(shutil.rmtree, web_sources.RAW_CACHE_DIR, True)

    def test_a_fetched_page_is_reused_from_disk(self) -> None:
        calls = []

        def fake_fetch(candidate, provider=None):
            calls.append(candidate["url"])
            return {"url": candidate["url"], "text": "inhoud", "title": "T", "status_code": 200}

        with mock.patch.object(web_sources, "fetch_web_candidate", fake_fetch):
            first = web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/a"})
            second = web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/a"})

        self.assertEqual(["https://duo.nl/a"], calls, "de tweede keer hoort van schijf te komen")
        self.assertEqual(first["text"], second["text"])

    def test_the_cache_keeps_only_the_page_not_the_question(self) -> None:
        """Candidate fields differ per question and must not be cached per URL."""
        def fake_fetch(candidate, provider=None):
            return {"url": candidate["url"], "text": "inhoud", "discovery_strategy": "seed_urls"}

        with mock.patch.object(web_sources, "fetch_web_candidate", fake_fetch):
            web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/b", "discovery_strategy": "seed_urls"})
        stored = json.loads(web_sources._raw_cache_path("https://duo.nl/b").read_text(encoding="utf-8"))
        self.assertIn("text", stored)
        self.assertNotIn("discovery_strategy", stored)

    def test_an_explicit_provider_is_never_served_from_cache(self) -> None:
        """Passing a provider says where it must come from; disk is not that."""
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False
            calls = 0

            def search(self, query, *, allowed_domains=None, max_results=5):
                return []

            def fetch(self, url):
                Provider.calls += 1
                return {"url": url, "text": "van de provider", "status_code": 200}

        provider = Provider()
        web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/c"}, provider=provider)
        web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/c"}, provider=provider)
        self.assertEqual(2, Provider.calls)

    def test_a_stale_copy_is_refetched(self) -> None:
        import os

        def fake_fetch(candidate, provider=None):
            return {"url": candidate["url"], "text": "nieuw", "status_code": 200}

        path = web_sources._raw_cache_path("https://duo.nl/d")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": "oud"}), encoding="utf-8")
        old = time.time() - web_sources.RAW_CACHE_TTL_SECONDS - 60
        os.utime(path, (old, old))

        with mock.patch.object(web_sources, "fetch_web_candidate", fake_fetch):
            result = web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/d"})
        self.assertEqual("nieuw", result["text"])

    def test_a_corrupt_cache_entry_does_not_break_the_answer(self) -> None:
        path = web_sources._raw_cache_path("https://duo.nl/e")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{niet eens json", encoding="utf-8")

        with mock.patch.object(web_sources, "fetch_web_candidate",
                               lambda candidate, provider=None: {"url": candidate["url"], "text": "vers"}):
            self.assertEqual("vers", web_sources.fetch_web_candidate_cached({"url": "https://duo.nl/e"})["text"])

    def test_candidates_are_fetched_in_parallel(self) -> None:
        """Fifteen pages one after another is where the seconds went."""
        import threading

        active = []
        peak = [0]
        lock = threading.Lock()

        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False

            def search(self, query, *, allowed_domains=None, max_results=5):
                return []

            def fetch(self, url):
                with lock:
                    active.append(url)
                    peak[0] = max(peak[0], len(active))
                time.sleep(0.05)
                with lock:
                    active.remove(url)
                return {"url": url, "text": "inhoud", "status_code": 200, "title": url}

        web_sources.build_web_context_with_candidates("Wat is een onechte neveninschrijving?", provider=Provider())
        self.assertGreater(peak[0], 1, "de fetches liepen nog steeds op een rij")

    def test_one_failing_source_does_not_take_the_others_down(self) -> None:
        class Provider:
            name = "fixture"
            requires_api_key = False
            is_paid_or_usage_based = False

            def search(self, query, *, allowed_domains=None, max_results=5):
                return []

            def fetch(self, url):
                raise RuntimeError("offline")

        result = web_sources.build_web_context_with_candidates("Wat is een onechte neveninschrijving?", provider=Provider())
        self.assertEqual([], result["web_context"])
        self.assertTrue(result["rejected_web_candidates"])
