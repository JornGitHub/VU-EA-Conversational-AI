"""Drive the phone answer layer in a real browser.

`docs/zoek.html` is the only route that works when the laptop is unreachable,
so its answers are not decoration: on eduroam they are the whole product. The
claim it makes about itself - every fact comes literally from the
documentation, nothing is generated - is only worth something if it is checked,
so that is what these tests do, against the real export, in a real browser,
including with the network switched off.

Needs Playwright with Chromium. Without it the module skips instead of failing;
the rest of the suite still guards the page's text.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import socketserver
import threading
import unittest
from pathlib import Path

DOCS = Path("docs").resolve()
DATA = DOCS / "data" / "definities.json"


def _chromium_path() -> str | None:
    """Return a Chromium to launch, or None to let Playwright pick its own.

    A normal `playwright install chromium` needs nothing here. This only helps
    an environment where the browser on disk is not the build the Python
    package expects.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not root.is_dir():
        return None
    found = sorted(root.glob("chromium-*/chrome-linux/chrome"))
    return str(found[-1]) if found else None


class _Server:
    """A plain HTTP server over docs/, because file:// has no service worker."""

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            """Elke opgehaalde icoon op stderr maakt een testrun onleesbaar."""

    def __init__(self) -> None:
        handler = functools.partial(self._Quiet, directory=str(DOCS))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/zoek.html"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class AnswerTests(unittest.TestCase):
    """Ask the page real questions and read what it puts on the screen."""

    @classmethod
    def setUpClass(cls) -> None:
        if not DATA.exists():
            raise unittest.SkipTest("docs/data/definities.json niet gebouwd")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("playwright ontbreekt: pip install playwright && playwright install chromium")

        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(executable_path=_chromium_path())
        except Exception as exc:  # noqa: BLE001 - elke opstartfout betekent hetzelfde
            cls.playwright.stop()
            raise unittest.SkipTest(f"geen Chromium beschikbaar: {exc}")

        cls.server = _Server()
        cls.payload = json.loads(DATA.read_text(encoding="utf-8"))
        cls.entries = {entry["name"]: entry for entry in cls.payload["entries"]}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.errors: list[str] = []
        self.page = self.browser.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.goto(self.server.url)
        self.page.wait_for_function("window.__vuea !== undefined && document.querySelector('#q') !== null")
        self.page.wait_for_function("window.__vuea.compose('opleidingsvorm') !== null")

    def tearDown(self) -> None:
        self.assertEqual([], self.errors, "javascriptfout op de pagina")
        self.page.close()

    # ------------------------------------------------------------------ #

    def ask(self, question: str) -> str:
        """Type a question the way a user does and return the answer text."""
        self.page.fill("#q", question)
        self.page.wait_for_function(
            "document.querySelector('#answer').textContent.length >= 0"
        )
        return self.page.eval_on_selector("#answer", "el => el.innerText")

    def compose(self, question: str) -> dict | None:
        return self.page.evaluate("query => window.__vuea.compose(query)", question)

    # ------------------------------------------------------------------ #

    def test_a_definition_question_is_answered_with_the_documented_text(self) -> None:
        answer = self.ask("wat is een internationale student?")
        self.assertIn("Internationale student", answer)
        self.assertIn(self.entries["Internationale student"]["text"], answer)

    def test_a_values_question_lists_every_documented_code(self) -> None:
        answer = self.ask("welke waarden heeft opleidingsvorm?")
        for value in self.entries["Opleidingsvorm"]["codes"]:
            self.assertIn(value["meaning"], answer, value)
        self.assertIn("3 gedocumenteerde waarden", answer)

    def test_a_code_question_names_the_meaning_of_that_code(self) -> None:
        answer = self.ask("wat betekent code 6 bij croho-onderdeel actuele opleiding?")
        self.assertIn("economie", answer)

    def test_an_undocumented_code_is_reported_as_missing_not_invented(self) -> None:
        """The failure mode to avoid is a plausible meaning for a code that has none."""
        answer = self.ask("wat betekent code 99 bij opleidingsvorm")
        self.assertIn("Code 99 staat niet in de codelijst", answer)
        self.assertNotIn("99 in Opleidingsvorm betekent", answer)

    def test_a_location_question_names_the_files(self) -> None:
        answer = self.ask("in welk bestand vind ik opleidingsvorm?")
        self.assertIn("Inschrijvingen_aggr_UNL_2025.csv", answer)

    def test_a_field_number_question_names_the_number_and_the_file(self) -> None:
        answer = self.ask("welk veldnummer heeft croho-onderdeel actuele opleiding?")
        field = self.entries["Croho-onderdeel actuele opleiding"]
        self.assertIn(f"veld {field['number']}", answer)
        self.assertIn(field["dataset"], answer)

    def test_a_comparison_shows_both_sides_and_admits_the_source_does_not_compare(self) -> None:
        answer = self.ask("verschil tussen actuele instelling en echte neveninschrijving")
        self.assertIn("Actuele instelling", answer)
        self.assertIn("Echte neveninschrijving", answer)
        self.assertIn("niet naast elkaar", answer)

    def test_nonsense_gets_no_answer_at_all(self) -> None:
        answer = self.ask("zxqwv")
        self.assertIn("Hier staat niets over", answer)

    def test_nonsense_does_not_inherit_the_previous_subject(self) -> None:
        """A subject sticks around for follow-ups; it must not stick to noise."""
        self.ask("welke waarden heeft opleidingsvorm?")
        answer = self.ask("zxqwv")
        self.assertNotIn("Opleidingsvorm", answer)
        self.assertIn("Hier staat niets over", answer)

    def test_a_follow_up_question_keeps_the_previous_subject(self) -> None:
        self.ask("wat is opleidingsvorm")
        answer = self.ask("en de waarden daarvan?")
        self.assertIn("vervolgvraag over opleidingsvorm", answer.lower())
        self.assertIn("voltijd", answer)

    def test_a_follow_up_about_location_keeps_the_previous_subject(self) -> None:
        self.ask("wat is verblijfsjaar")
        answer = self.ask("waar staat dat?")
        self.assertIn("vervolgvraag over verblijfsjaar", answer.lower())
        self.assertIn("1cyferho_2025_v1.0.asc", answer)

    def test_a_new_question_is_not_swallowed_by_the_previous_subject(self) -> None:
        """"die" and "dat" are far too ordinary in Dutch to mean "the previous one"."""
        self.ask("wat is opleidingsvorm")
        answer = self.ask("wat is de indicatie die op peildatum geldt")
        self.assertNotIn("vervolgvraag", answer.lower())
        self.assertNotIn("Opleidingsvorm", answer)

    def test_a_question_made_only_of_filler_words_gets_no_subject(self) -> None:
        """'veld' is an alias of all 54 fields; as a subject it picks one at random."""
        self.assertEqual("", self.page.evaluate("() => window.__vuea.subjectOf('wat is het veld')"))
        self.assertEqual("", self.page.evaluate("() => window.__vuea.subjectOf('de term')"))

    def test_a_table_fragment_is_never_presented_as_a_definition(self) -> None:
        """Some source text was cut mid-table; answering from it would be a lie."""
        blocked = [e["name"] for e in self.payload["entries"] if e.get("answerable") is False]
        self.assertTrue(blocked, "geen enkel item is als onbruikbaar gemarkeerd")
        # "Instroom" is in de bron een uitgeschreven layouttabel. EOI-cohort
        # stond hier eerder; die is nu opgeschoond en wél te beantwoorden.
        answer = self.ask("wat is Instroom")
        self.assertIn("tabelfragment", answer)
        self.assertNotIn(self.entries["Instroom"]["text"][:60], answer)

    def test_every_example_question_actually_gets_an_answer(self) -> None:
        """An example that returns "hier staat niets over" is worse than none."""
        examples = self.page.evaluate(
            "() => [...document.querySelectorAll('#suggest button')].map(b => b.textContent)"
        )
        self.assertGreaterEqual(len(examples), 4, examples)
        for example in examples:
            self.assertIn("?", example + "?", example)  # het zijn vragen, geen losse termen
            model = self.compose(example)
            self.assertTrue(model and model.get("ok"), f"geen antwoord op voorbeeld: {example}")

    def test_the_examples_are_phrased_as_questions(self) -> None:
        """A bare term hides the fact that the page answers questions now."""
        examples = self.page.evaluate(
            "() => [...document.querySelectorAll('#suggest button')].map(b => b.textContent)"
        )
        asking = [e for e in examples if e.strip().endswith("?") or " " in e.strip()]
        self.assertEqual(len(examples), len(asking), examples)

    def test_tapping_an_example_shows_its_answer(self) -> None:
        self.page.click("#suggest button")
        answer = self.page.eval_on_selector("#answer", "el => el.innerText")
        self.assertIn("ANTWOORD", answer.upper())
        self.assertNotIn("Hier staat niets over", answer)

    def test_an_answer_shows_the_code_list_that_was_buried_in_the_prose(self) -> None:
        """This entry was 2407 characters of flattened table."""
        answer = self.ask("Sleutel domein actuele opleiding")
        self.assertIn("Persoonsgebonden nummer + inschrijvingsjaar", answer)
        self.assertIn("hoofdinschrijving binnen het domein opleiding actueel equivalent", answer)
        self.assertNotIn("Mogelijke waarden:", answer)
        self.assertNotIn("Soort inschrijving actuele instelling", answer)

    def test_a_result_list_does_not_unroll_every_code_list(self) -> None:
        """Seven hits with fourteen codes each is 18.000 pixels of scrolling."""
        self.page.fill("#q", "Sleutel domein actuele opleiding")
        self.page.wait_for_timeout(150)
        height = self.page.evaluate("() => document.documentElement.scrollHeight")
        self.assertLess(height, 12000, f"resultatenlijst is {height}px lang")
        collapsed = self.page.eval_on_selector_all(
            "#results .hit details summary", "els => els.map(e => e.textContent)")
        self.assertTrue(any("mogelijke waarden" in text for text in collapsed), collapsed)

    def test_raw_source_text_is_not_presented_as_a_definition(self) -> None:
        self.page.fill("#q", "Mogelijke waarden")
        self.page.wait_for_timeout(150)
        first = self.page.eval_on_selector("#results .hit", "el => el.innerText")
        self.assertIn("Ruwe brontekst", first)
        self.assertIn("Toon de brontekst", first)

    def test_the_question_words_do_not_end_up_in_the_search(self) -> None:
        """'wat is een X' must find X, not whatever matches 'wat'."""
        self.assertEqual("internationale student", self.page.evaluate(
            "() => window.__vuea.subjectOf('Wat is een internationale student?')"))
        self.assertEqual("opleidingsvorm", self.page.evaluate(
            "() => window.__vuea.subjectOf('In welk bestand staat het veld opleidingsvorm?')"))

    def test_every_fact_in_an_answer_comes_verbatim_from_the_documentation(self) -> None:
        """The page's own claim, checked: it copies facts, it does not write them.

        Blocks of kind fact/list/codes/meaning carry source text. Every one of
        them must appear literally somewhere in the published data. Only 'line'
        blocks are sentences of the page itself, and those carry nothing but
        names and numbers that are in the data too.
        """
        pool = set()

        def collect(value: object) -> None:
            if isinstance(value, str):
                pool.add(value)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(self.payload)

        questions = [
            "wat is een internationale student?",
            "wat is opleidingsvorm",
            "welke waarden heeft opleidingsvorm?",
            "wat betekent code 6 bij croho-onderdeel actuele opleiding?",
            "in welk bestand vind ik opleidingsvorm?",
            "welk veldnummer heeft croho-onderdeel actuele opleiding?",
            "verschil tussen actuele instelling en echte neveninschrijving",
            "wat is verblijfsjaar",
            "wat is uitval",
            "wat is studiesucces",
            "wat betekent onechte neveninschrijving",
            "welke codes heeft croho-onderdeel actuele opleiding",
            "waar vind ik nationaliteit",
            "wat is opleidingsfase",
            "wat is instroom",
        ]
        checked = 0
        for question in questions:
            model = self.compose(question)
            if not model or not model.get("ok"):
                continue
            for block in model["blocks"]:
                if block["kind"] in {"fact", "meaning"}:
                    self.assertIn(block["text"], pool, f"{question}: {block['text'][:70]!r}")
                    checked += 1
                elif block["kind"] == "list":
                    for item in block["items"]:
                        self.assertIn(item, pool, f"{question}: {item[:70]!r}")
                        checked += 1
                elif block["kind"] == "codes":
                    for item in block["items"]:
                        self.assertIn(item["meaning"], pool, f"{question}: {item['meaning'][:70]!r}")
                        checked += 1
        self.assertGreater(checked, 30, "te weinig feiten gecontroleerd om iets te bewijzen")

    def test_the_answers_still_work_with_the_network_switched_off(self) -> None:
        """The point of the whole page: no laptop, no wifi, still an answer."""
        self.page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        self.page.wait_for_function("() => navigator.serviceWorker.controller !== null")
        self.page.context.set_offline(True)
        try:
            self.page.reload()
            self.page.wait_for_function("window.__vuea !== undefined")
            self.page.wait_for_function("window.__vuea.compose('opleidingsvorm') !== null")
            answer = self.ask("welke waarden heeft opleidingsvorm?")
            self.assertIn("voltijd", answer)
        finally:
            self.page.context.set_offline(False)


class BackToLauncherTests(unittest.TestCase):
    """Getting back to the start page, on whatever host this is served from.

    The link is relative, so it follows the host by itself - jorngithub,
    vusaverse or file://. The part that needs proving is that it still works
    with the network off, because that is the situation this whole page exists
    for: an installed app on a phone that cannot reach anything.
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("playwright ontbreekt: pip install playwright && playwright install chromium")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(executable_path=_chromium_path())
        except Exception as exc:  # noqa: BLE001
            cls.playwright.stop()
            raise unittest.SkipTest(f"geen Chromium beschikbaar: {exc}")
        cls.server = _Server()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.page = self.browser.new_page()
        self.page.goto(self.server.url)
        self.page.wait_for_function("window.__vuea !== undefined")

    def tearDown(self) -> None:
        self.page.close()

    def test_the_link_sits_above_the_page_title(self) -> None:
        """In the footer it was 9.000 pixels below a phone-sized result list."""
        order = self.page.evaluate(
            "() => {\n"
            "  const link = document.querySelector('.backlink');\n"
            "  const title = document.querySelector('h1');\n"
            "  return link.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING ? 'ervoor' : 'erna';\n"
            "}"
        )
        self.assertEqual("ervoor", order)

    def test_the_link_is_relative_so_it_follows_the_host(self) -> None:
        href = self.page.eval_on_selector(".backlink", "el => el.getAttribute('href')")
        self.assertEqual("./", href)
        resolved = self.page.eval_on_selector(".backlink", "el => el.href")
        self.assertTrue(resolved.startswith(f"http://127.0.0.1:{self.server.httpd.server_address[1]}/"), resolved)
        self.assertNotIn("github.io", resolved)

    def test_it_is_a_comfortable_tap_target(self) -> None:
        height = self.page.eval_on_selector(".backlink", "el => el.getBoundingClientRect().height")
        self.assertGreaterEqual(height, 44, "te klein om op een telefoon te raken")

    def test_clicking_it_opens_the_start_page(self) -> None:
        self.page.click(".backlink")
        self.page.wait_for_load_state()
        self.assertIn("VU EA Conversational AI", self.page.eval_on_selector("h1", "el => el.textContent"))

    def test_it_still_works_with_the_network_off(self) -> None:
        """An installed app on a phone with no signal must not hit a dead end."""
        self.page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        self.page.wait_for_function("() => navigator.serviceWorker.controller !== null")
        # De cache wordt bij install gevuld; even wachten tot de startpagina er staat.
        self.page.wait_for_function(
            "() => caches.keys()"
            ".then(names => Promise.all(names.map(n => caches.open(n).then(c => c.match('./index.html')))))"
            ".then(hits => hits.some(Boolean))"
        )
        self.page.context.set_offline(True)
        try:
            self.page.click(".backlink")
            self.page.wait_for_load_state()
            self.assertIn("VU EA Conversational AI", self.page.eval_on_selector("h1", "el => el.textContent"))
        finally:
            self.page.context.set_offline(False)


if __name__ == "__main__":
    unittest.main()
