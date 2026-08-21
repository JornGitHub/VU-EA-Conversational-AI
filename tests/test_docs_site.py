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
        primary = windows_panel.split("<details")[0]
        self.assertIn("git clone", primary)
        self.assertIn("python -m venv .venv", primary)
        self.assertIn(r".\.venv\Scripts\python.exe main.py", primary)
        self.assertNotIn("| iex", primary)

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


if __name__ == "__main__":
    unittest.main()
