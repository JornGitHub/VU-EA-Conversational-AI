"""Guard the GitHub Pages start page and the scripts it hands out.

These are static checks: they catch a renamed script, a changed URL or a missing
download long before a colleague runs into it.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

DOCS = Path("docs")
PAGE = DOCS / "index.html"
PAGE_TEXT = PAGE.read_text(encoding="utf-8")
BASE_URL = "https://jorngithub.github.io/VU-EA-Conversational-AI"
REPO_URL = "https://github.com/JornGitHub/VU-EA-Conversational-AI"
README_TEXT = Path("README.md").read_text(encoding="utf-8")


class SiteFilesTests(unittest.TestCase):
    def test_every_published_file_exists(self) -> None:
        for name in ("index.html", "start.sh", "start-windows.ps1", "start-windows.bat", "start-macos.command", ".nojekyll"):
            self.assertTrue((DOCS / name).exists(), f"docs/{name} ontbreekt")

    def test_page_links_and_downloads_resolve_to_real_files(self) -> None:
        for href in re.findall(r'href="([^"#:]+)"', PAGE_TEXT):
            self.assertTrue((DOCS / href).exists(), f"dode link op de pagina: {href}")

    def test_hosted_script_urls_point_at_published_files(self) -> None:
        urls = set(re.findall(rf"{re.escape(BASE_URL)}/([\w.-]+)", PAGE_TEXT))
        self.assertTrue(urls, "de pagina noemt geen enkel startscript")
        for name in urls:
            self.assertTrue((DOCS / name).exists(), f"pagina verwijst naar ontbrekend bestand: {name}")


class StartCommandTests(unittest.TestCase):
    def test_page_offers_a_command_per_operating_system(self) -> None:
        for panel in ("panel-windows", "panel-macos", "panel-linux"):
            self.assertIn(panel, PAGE_TEXT)
        self.assertIn(f"curl -fsSL {BASE_URL}/start.sh | bash", PAGE_TEXT)

    def test_windows_leads_with_commands_that_need_no_remote_script(self) -> None:
        """Managed Windows laptops block scripts executed straight from the web.

        The tester hit "This script contains malicious content and has been blocked
        by your antivirus software", so the primary Windows route must be plain
        commands: clone, venv, run.
        """
        windows_panel = PAGE_TEXT.split('id="panel-windows"')[1].split("</section>")[0]
        # Everything up to the optional script route: that is what a tester follows.
        primary = windows_panel.split("Liever \u00e9\u00e9n regel")[0]
        self.assertIn("git clone", primary)
        self.assertIn("python -m venv .venv", primary)
        self.assertIn(r".\.venv\Scripts\python.exe main.py", primary)
        self.assertNotIn("| iex", primary)
        self.assertNotIn("start-windows.ps1", primary)

    def test_windows_checks_python_before_the_install_commands(self) -> None:
        """A dead python.exe makes every later command fail with a confusing error.

        The tester saw "Program 'python.exe' failed to run: The system cannot find
        the path specified", so the page must verify Python first and explain the
        Microsoft Store alias before handing out the clone/venv block.
        """
        windows_panel = PAGE_TEXT.split('id="panel-windows"')[1].split("</section>")[0]
        check = windows_panel.index('id="code-windows-check"')
        install = windows_panel.index('id="code-windows"')
        self.assertLess(check, install, "de Python-controle moet vóór het installatieblok staan")
        self.assertIn("python --version", windows_panel)

    def test_page_explains_the_microsoft_store_alias(self) -> None:
        self.assertIn("WindowsApps", PAGE_TEXT)
        self.assertIn("App-uitvoeringsaliassen", PAGE_TEXT)
        self.assertIn("where.exe python", PAGE_TEXT)
        self.assertIn("py -0p", PAGE_TEXT)

    def test_page_offers_a_full_path_fallback_for_python(self) -> None:
        self.assertIn("LOCALAPPDATA", PAGE_TEXT)
        self.assertIn("-m venv .venv", PAGE_TEXT)

    def test_page_covers_the_errors_testers_actually_reported(self) -> None:
        for message in (
            "Program 'python.exe' failed to run",
            "destination path",
            "Windows Security",
            "No suitable Python runtime found",
        ):
            self.assertIn(message, PAGE_TEXT, f"pagina noemt niet: {message}")

    def test_every_copy_button_points_at_an_existing_block(self) -> None:
        targets = set(re.findall(r'data-copy="([^"]+)"', PAGE_TEXT))
        ids = set(re.findall(r'<pre id="([^"]+)"', PAGE_TEXT))
        self.assertTrue(targets, "de pagina heeft geen kopieerknoppen")
        self.assertEqual(set(), targets - ids, "kopieerknop zonder codeblok")
        self.assertEqual(set(), ids - targets, "codeblok zonder kopieerknop")

    def test_the_one_line_script_route_downloads_before_running(self) -> None:
        self.assertNotIn("start-windows.ps1 | iex", PAGE_TEXT)
        self.assertIn("start-windows.ps1 -OutFile start.ps1", PAGE_TEXT)
        self.assertIn("-File .\\start.ps1", PAGE_TEXT)

    def test_page_explains_the_antivirus_block(self) -> None:
        self.assertIn("geblokkeerd", PAGE_TEXT)
        self.assertIn("virusscanner", PAGE_TEXT)

    def test_double_click_launchers_use_the_same_hosted_scripts(self) -> None:
        self.assertIn(f"{BASE_URL}/start.sh", (DOCS / "start-macos.command").read_text(encoding="utf-8"))
        self.assertIn(f"{BASE_URL}/start-windows.ps1", (DOCS / "start-windows.bat").read_text(encoding="utf-8"))

    def test_windows_launcher_downloads_before_running(self) -> None:
        """Piping a remote script into iex is what the antivirus blocks."""
        launcher = (DOCS / "start-windows.bat").read_text(encoding="utf-8")
        self.assertIn("-OutFile", launcher)
        self.assertIn("-File", launcher)
        # Comments may explain the pattern; no executable line may use it.
        commands = [line for line in launcher.splitlines() if not line.strip().upper().startswith("REM")]
        self.assertNotIn("| iex", "\n".join(commands))

    def test_bootstrap_scripts_default_to_this_repository(self) -> None:
        for name in ("start.sh", "start-windows.ps1"):
            self.assertIn(f"{REPO_URL}.git", (DOCS / name).read_text(encoding="utf-8"), name)

    def test_bootstrap_scripts_are_overridable_for_forks_and_tests(self) -> None:
        for name in ("start.sh", "start-windows.ps1"):
            text = (DOCS / name).read_text(encoding="utf-8")
            for variable in ("VUEA_REPO_URL", "VUEA_DIR", "VUEA_BRANCH"):
                self.assertIn(variable, text, f"{name} mist {variable}")

    def test_shell_script_syntax_is_valid(self) -> None:
        for name in ("start.sh", "start-macos.command"):
            result = subprocess.run(["bash", "-n", str(DOCS / name)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, f"{name}: {result.stderr}")

    def test_scripts_run_the_single_entry_point(self) -> None:
        """The page promises that main.py does the rest; the scripts must call it."""
        self.assertIn("python main.py", (DOCS / "start.sh").read_text(encoding="utf-8"))
        self.assertIn("main.py", (DOCS / "start-windows.ps1").read_text(encoding="utf-8"))

    def test_windows_script_resolves_one_python_path(self) -> None:
        """Passing a command plus flags broke when py existed without a runtime.

        The script must resolve a single absolute interpreter path, skip the
        Microsoft Store stub, and judge a candidate by its output rather than by
        an exit code that Windows PowerShell 5.1 reports inconsistently.
        """
        script = (DOCS / "start-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("function Resolve-PythonExe", script)
        self.assertIn("WindowsApps", script)
        self.assertIn("sys.executable", script)
        self.assertNotIn("Arguments = ", script)
        self.assertNotIn("$LASTEXITCODE", script)

    def test_windows_script_names_the_store_alias_when_that_is_all_it_finds(self) -> None:
        """"Geen Python gevonden" is unhelpful when a dead python.exe is right there."""
        script = (DOCS / "start-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("SawStoreStub", script)
        self.assertIn("App-uitvoeringsaliassen", script)
        self.assertIn("failed to run", script)


class PageContentTests(unittest.TestCase):
    def test_page_is_self_contained(self) -> None:
        """GitHub Pages serves this as-is; no external scripts or stylesheets."""
        self.assertNotIn("<script src=", PAGE_TEXT)
        self.assertNotIn('rel="stylesheet"', PAGE_TEXT)

    def test_page_states_that_it_cannot_install_anything_itself(self) -> None:
        self.assertIn("Deze pagina start zelf niets", PAGE_TEXT)

    def test_page_names_the_app_and_its_requirements(self) -> None:
        self.assertIn("VU EA Conversational AI", PAGE_TEXT)
        self.assertIn("Python 3.10+", PAGE_TEXT)
        self.assertIn("Ollama", PAGE_TEXT)
        self.assertIn("localhost:8501", PAGE_TEXT)

    def test_page_supports_both_colour_schemes(self) -> None:
        self.assertIn("prefers-color-scheme: dark", PAGE_TEXT)


class ReadmeStaysInSyncTests(unittest.TestCase):
    """The README is the fallback for anyone who never opens the start page."""

    def test_readme_documents_the_windows_errors_the_page_covers(self) -> None:
        for message in (
            "Program 'python.exe' failed to run",
            "App-uitvoeringsaliassen",
            "where.exe python",
            "Windows Security",
        ):
            self.assertIn(message, README_TEXT, f"README noemt niet: {message}")

    def test_readme_shows_the_same_windows_start_commands_as_the_page(self) -> None:
        for command in ("python --version", "python -m venv .venv", r".\.venv\Scripts\python.exe main.py"):
            self.assertIn(command, README_TEXT, f"README mist startcommando: {command}")

    def test_readme_points_at_the_docs_folder_for_pages(self) -> None:
        self.assertIn("map `/docs`", README_TEXT)


if __name__ == "__main__":
    unittest.main()
