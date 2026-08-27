"""Drive the development-status panel on the start page in a real browser.

The panel talks to the GitHub API, so every interesting state is a response
this project does not control: rate limited, offline, a repository with no
published deployment. Those are mocked here rather than waited for, which also
keeps the suite off the network.

The property that matters most is the one that is easy to lose: nothing is
fetched until someone opens the panel. The API allows 60 unauthenticated
requests per hour per IP, and on a university network that IP is shared by
everyone in the building.

Needs Playwright with Chromium; skips cleanly without it.
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

MAIN_SHA = "14a0b6f95196991ba41c622be0702d3fbaca7798"
OLD_SHA = "07b5590aa11122233344455566677788899900011"

COMMIT = {
    "sha": MAIN_SHA,
    "commit": {
        "message": "Merge pull request #35 from JornGitHub/claude/clean-extracted-definitions\n\nmeer",
        "committer": {"date": "2026-08-27T13:06:02Z"},
    },
}
PULLS = [
    {"number": 34, "title": "Een oudere merge", "merged_at": "2026-08-27T12:00:00Z",
     "html_url": "https://github.com/vusaverse/VU-EA-Conversational-AI/pull/34",
     "user": {"login": "JornGitHub"}},
    {"number": 36, "title": "Nooit gemerged", "merged_at": None,
     "html_url": "https://example.invalid/36", "user": {"login": "iemand"}},
    {"number": 35, "title": "Cut the extracted definitions", "merged_at": "2026-08-27T13:06:02Z",
     "html_url": "https://github.com/vusaverse/VU-EA-Conversational-AI/pull/35",
     "user": {"login": "JornGitHub"}},
]


def _chromium_path() -> str | None:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not root.is_dir():
        return None
    found = sorted(root.glob("chromium-*/chrome-linux/chrome"))
    return str(found[-1]) if found else None


class _Server:
    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            """Stil, anders verzuipt de testuitvoer in verzoeken."""

    def __init__(self) -> None:
        handler = functools.partial(self._Quiet, directory=str(DOCS))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/index.html"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class DevStatusTests(unittest.TestCase):
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
        self.errors: list[str] = []
        self.calls: list[str] = []
        self.page = self.browser.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))

    def tearDown(self) -> None:
        self.assertEqual([], self.errors, "javascriptfout op de pagina")
        self.page.close()

    # ------------------------------------------------------------------ #

    def serve(self, *, deployments=None, compare=None, fail: str = "") -> None:
        """Answer the GitHub API with canned data, and count what was asked."""
        def handler(route, request):
            self.calls.append(request.url)
            if fail == "limiet":
                route.fulfill(status=403, content_type="application/json",
                              body=json.dumps({"message": "API rate limit exceeded"}))
                return
            if fail == "stuk":
                route.abort()
                return
            url = request.url
            if "/commits/main" in url:
                payload = COMMIT
            elif "/pulls" in url:
                payload = PULLS
            elif "/deployments" in url:
                payload = deployments if deployments is not None else []
            elif "/compare/" in url:
                payload = compare or {"ahead_by": 0}
            else:
                route.fulfill(status=404, body="{}")
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        self.page.route("https://api.github.com/**", handler)
        self.page.goto(self.server.url)

    def open_panel(self) -> str:
        self.page.click("#devstatus summary")
        self.page.wait_for_function(
            "() => !/Bezig met ophalen|Openklappen/.test(document.querySelector('#devstatus-body').textContent)"
        )
        return self.page.eval_on_selector("#devstatus-body", "el => el.innerText")

    # ------------------------------------------------------------------ #

    def test_nothing_is_fetched_until_the_panel_is_opened(self) -> None:
        """60 requests per hour per IP, shared by a whole campus."""
        self.serve()
        self.page.wait_for_timeout(400)
        self.assertEqual([], self.calls, "de pagina belt GitHub zonder dat iemand erom vroeg")

    def test_an_up_to_date_site_says_so(self) -> None:
        self.serve(deployments=[{"sha": MAIN_SHA, "created_at": "2026-08-27T13:12:00Z"}])
        text = self.open_panel()
        self.assertIn("bij met main", text)
        self.assertIn("14a0b6f", text)
        self.assertNotIn("achter", text)

    def test_the_last_merged_pull_request_is_named(self) -> None:
        self.serve(deployments=[{"sha": MAIN_SHA, "created_at": "2026-08-27T13:12:00Z"}])
        text = self.open_panel()
        self.assertIn("#35", text)
        self.assertIn("Cut the extracted definitions", text)
        self.assertIn("JornGitHub", text)
        self.assertNotIn("Nooit gemerged", text, "een openstaande PR is geen merge")
        self.assertNotIn("Een oudere merge", text, "alleen de laatste hoort hier")

    def test_a_stale_site_says_how_far_behind(self) -> None:
        self.serve(deployments=[{"sha": OLD_SHA, "created_at": "2026-08-25T09:00:00Z"}],
                   compare={"ahead_by": 3})
        text = self.open_panel()
        self.assertIn("3 commits achter", text)
        self.assertIn("07b5590", text)

    def test_one_commit_behind_is_written_in_the_singular(self) -> None:
        self.serve(deployments=[{"sha": OLD_SHA, "created_at": "2026-08-25T09:00:00Z"}],
                   compare={"ahead_by": 1})
        self.assertIn("1 commit achter", self.open_panel())

    def test_without_deployment_information_it_says_so_instead_of_guessing(self) -> None:
        self.serve(deployments=[])
        text = self.open_panel()
        self.assertIn("niet vast te stellen", text)
        self.assertIn("#35", text, "de rest hoort er nog wel te staan")

    def test_a_rate_limited_api_is_explained(self) -> None:
        self.serve(fail="limiet")
        text = self.open_panel()
        self.assertIn("60 keer per uur", text)

    def test_a_failing_network_does_not_break_the_page(self) -> None:
        self.serve(fail="stuk")
        self.assertIn("Kon de status niet ophalen", self.open_panel())

    def test_a_failed_attempt_can_be_retried_by_reopening(self) -> None:
        self.serve(fail="stuk")
        self.open_panel()
        self.calls.clear()
        self.page.click("#devstatus summary")   # dicht
        self.page.click("#devstatus summary")   # en weer open
        self.page.wait_for_timeout(300)
        self.assertTrue(self.calls, "een mislukte poging blijft anders voorgoed mislukt")

    def test_the_second_look_comes_from_the_cache(self) -> None:
        self.serve(deployments=[{"sha": MAIN_SHA, "created_at": "2026-08-27T13:12:00Z"}])
        self.open_panel()
        first = len(self.calls)
        self.page.reload()
        self.open_panel()
        self.assertEqual(first, len(self.calls), "elke paginaweergave kost opnieuw API-budget")

    def test_a_pull_request_title_cannot_carry_markup_into_the_page(self) -> None:
        """Titles are typed by people; the panel renders text, never HTML."""
        evil = dict(PULLS[2])
        evil["title"] = "<img src=x onerror=alert(1)>klaar"
        PULLS[2] = evil
        try:
            self.serve(deployments=[{"sha": MAIN_SHA, "created_at": "2026-08-27T13:12:00Z"}])
            self.open_panel()
            self.assertEqual(0, self.page.eval_on_selector_all("#devstatus-body img", "e => e.length"))
            self.assertIn("<img src=x onerror=alert(1)>klaar",
                          self.page.eval_on_selector("#devstatus-body", "el => el.innerText"))
        finally:
            PULLS[2] = dict(evil, title="Cut the extracted definitions")


if __name__ == "__main__":
    unittest.main()
