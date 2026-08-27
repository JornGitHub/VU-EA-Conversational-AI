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
BASE_URL = "https://vusaverse.github.io/VU-EA-Conversational-AI"
REPO_URL = "https://github.com/vusaverse/VU-EA-Conversational-AI"
README_TEXT = Path("README.md").read_text(encoding="utf-8")


class PublishedHostTests(unittest.TestCase):
    """Where the published links point, and whether anything is there.

    Every URL in this project pointed at jorngithub.github.io, which returns
    404 for every path: the one-line installers, the phone page, the fallback
    the network diagnosis hands out when nothing else works. The suite did not
    notice, because BASE_URL in this file was the only place the host was
    written down and the tests compared it with itself.
    """

    SOURCES = (
        "README.md", "app_streamlit.py", "src/network_diagnosis.py",
        "docs/index.html", "docs/zoek.html", "docs/start.sh",
        "docs/start-windows.ps1", "docs/start-windows.bat", "docs/start-macos.command",
    )

    def test_every_published_link_uses_the_same_owner(self) -> None:
        """A half-finished rename leaves some links dead and looks fine."""
        wrong: list[str] = []
        for name in self.SOURCES:
            text = Path(name).read_text(encoding="utf-8")
            for url in re.findall(r"https://[\w.-]*github[\w.-]*/[\w./-]*", text):
                if "VU-EA-Conversational-AI" not in url:
                    continue
                if not url.startswith((BASE_URL, REPO_URL)):
                    wrong.append(f"{name}: {url}")
        self.assertEqual([], wrong, "links wijzen niet allemaal naar dezelfde eigenaar")

    def test_the_old_dead_host_is_gone(self) -> None:
        for name in self.SOURCES:
            self.assertNotIn(
                "jorngithub.github.io", Path(name).read_text(encoding="utf-8").lower(), name
            )

    def test_the_published_site_actually_answers(self) -> None:
        """The check that would have caught this. Skips without a network."""
        import urllib.error
        import urllib.request

        for path in ("", "/zoek.html", "/start.sh"):
            url = BASE_URL + path
            try:
                with urllib.request.urlopen(url, timeout=15) as response:
                    self.assertEqual(200, response.status, url)
            except urllib.error.HTTPError as error:
                self.fail(f"{url} geeft HTTP {error.code} - de gepubliceerde site is er niet")
            except OSError as error:  # geen netwerk, proxy, DNS: niets over te zeggen
                self.skipTest(f"geen netwerk om {url} te controleren ({error})")


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

    def test_every_panel_leads_with_a_route_that_installs_everything(self) -> None:
        """Whatever comes first must be the route that needs no manual steps."""
        for panel, expected in (
            ("panel-windows", "start-windows.bat"),
            ("panel-macos", "start-macos.command"),
            ("panel-linux", "start.sh"),
        ):
            section = PAGE_TEXT.split(f'id="{panel}"')[1].split("</section>")[0]
            primary = section.split("<details")[0]
            self.assertIn(expected, primary, f"{panel} leidt niet met de automatische route")

    def test_windows_leads_with_download_and_collapses_powershell(self) -> None:
        """Windows follows the same download-first layout as macOS and Linux."""
        windows = PAGE_TEXT.split('id="panel-windows"')[1].split("</section>")[0]
        primary, first_details = windows.split("<details", 1)
        self.assertIn('href="start-windows.bat" download', primary)
        self.assertNotIn('id="code-windows-script"', primary)
        self.assertIn("PowerShell-regels kopiëren en plakken?", first_details)
        self.assertIn('id="code-windows-script"', first_details)

    def test_every_panel_still_offers_the_double_click_launcher(self) -> None:
        """Not everyone wants a terminal; the launcher stays one click away."""
        for panel, launcher in (
            ("panel-windows", "start-windows.bat"),
            ("panel-macos", "start-macos.command"),
            ("panel-linux", "start.sh"),
        ):
            section = PAGE_TEXT.split(f'id="{panel}"')[1].split("</section>")[0]
            self.assertIn(f'href="{launcher}" download', section, f"{panel} mist de downloadknop")
            self.assertIn("btn-primary", section, f"{panel}: geen knop")

    def test_page_explains_that_a_blocked_launcher_is_policy(self) -> None:
        """The tester's .bat was refused outright, with no "run anyway" offered."""
        self.assertIn("Toch uitvoeren", PAGE_TEXT)
        self.assertIn("organisatie", PAGE_TEXT)

    def test_the_manual_windows_commands_survive_as_a_fallback(self) -> None:
        """Managed Windows laptops block every downloaded script.

        The tester hit both "This script contains malicious content" and a hard
        Windows Security block, so typing the commands by hand has to stay
        available and reachable, even though it is no longer the first thing shown.
        """
        windows_panel = PAGE_TEXT.split('id="panel-windows"')[1].split("</section>")[0]
        fallback = windows_panel.split("Wordt alles geblokkeerd")[1]
        self.assertIn("git clone", fallback)
        self.assertIn("python -m venv .venv", fallback)
        self.assertIn(r".\.venv\Scripts\python.exe main.py", fallback)
        self.assertNotIn("| iex", fallback)

    def test_the_manual_route_checks_python_before_the_install_commands(self) -> None:
        """A dead python.exe makes every later command fail with a confusing error.

        The tester saw "Program 'python.exe' failed to run: The system cannot find
        the path specified", so whoever types the commands by hand must verify
        Python first rather than after the clone/venv block.
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

    def test_page_separates_no_python_from_a_shadowed_python(self) -> None:
        """`where.exe python` says different things on different laptops.

        Only a WindowsApps path means no Python is installed at all; a real path
        next to it means the alias merely shadows it. The fixes are different, so
        the page must distinguish the two instead of giving one recipe.
        """
        block = PAGE_TEXT.split('data-copy="code-windows-where"')[1].split("</details>")[0]
        self.assertIn("Alleen", block)
        self.assertIn("geen", block)
        self.assertIn("App-uitvoeringsaliassen", block)
        self.assertIn("winget install", block)

    def test_wide_tables_stack_on_a_phone(self) -> None:
        """A three-column table pushed the whole page 411px sideways at 390px.

        The fix is a stacked layout on narrow screens, which only reads correctly
        when every cell carries its own label. Any table with prose in it needs
        the treatment, not just the one that first overflowed.
        """
        self.assertIn("table.stacks thead { display: none; }", PAGE_TEXT)
        self.assertIn("@media (max-width: 640px)", PAGE_TEXT)
        self.assertIn("content: attr(data-label)", PAGE_TEXT)
        self.assertIn("overflow-wrap: anywhere", PAGE_TEXT)

        tables = re.findall(r"<table([^>]*)>", PAGE_TEXT)
        self.assertTrue(tables, "de pagina heeft geen tabellen")
        for attributes in tables:
            self.assertIn('class="stacks"', attributes, "tabel zonder gestapelde weergave op mobiel")

        for table in PAGE_TEXT.split('<table class="stacks"')[1:]:
            body = table.split("</table>")[0]
            headers = re.findall(r"<th>([^<]+)</th>", body)
            cells = re.findall(r"<td([^>]*)>", body)
            self.assertEqual(0, len(cells) % len(headers), "rijen met een afwijkend aantal cellen")
            for attributes in cells:
                self.assertIn("data-label=", attributes, "cel zonder label valt weg in de gestapelde weergave")

    def test_page_tells_readers_the_version_folder_is_theirs_to_check(self) -> None:
        """The fallback path is copied verbatim, so the variable part must be flagged."""
        block = PAGE_TEXT.split('data-copy="code-windows-fullpath"')[1].split("</details>")[0]
        self.assertIn("Python313", block, "de pagina noemt geen andere versiemap als voorbeeld")
        self.assertIn("py -0p", block)

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

    def test_scripts_install_what_is_missing_instead_of_only_reporting_it(self) -> None:
        """The whole point of the starter: no manual diagnosis, no manual install."""
        windows = (DOCS / "start-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("function Install-Python", windows)
        self.assertIn("winget install", windows)
        self.assertIn("python.org/ftp/python", windows, "geen terugval als winget ontbreekt")
        self.assertIn("Git.Git", windows)
        self.assertIn("Ollama.Ollama", windows)

        posix = (DOCS / "start.sh").read_text(encoding="utf-8")
        self.assertIn("package_install", posix)
        for manager in ("brew install", "apt-get install", "dnf install", "pacman", "zypper"):
            self.assertIn(manager, posix, f"start.sh kent {manager} niet")
        self.assertIn("ollama.com/install.sh", posix)

    def test_installing_can_be_switched_off(self) -> None:
        """Installing software is a real change; it needs a documented opt-out."""
        for name in ("start.sh", "start-windows.ps1"):
            self.assertIn("VUEA_NO_INSTALL", (DOCS / name).read_text(encoding="utf-8"), name)

    def test_windows_script_finds_python_outside_path(self) -> None:
        """`where.exe python` by hand is exactly what the script should replace.

        It searches the standard install folders and refreshes PATH from the
        registry, so a fresh install works without opening a new PowerShell.
        """
        script = (DOCS / "start-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("LOCALAPPDATA", script)
        self.assertIn("Python3*", script)
        self.assertIn("function Update-PathFromRegistry", script)

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


class PhoneTests(unittest.TestCase):
    """A tester downloaded the .bat on an iPhone and nothing happened."""

    def test_page_says_the_app_cannot_run_on_a_phone(self) -> None:
        self.assertIn("Kan het op een telefoon?", PAGE_TEXT)
        self.assertIn("iOS", PAGE_TEXT)

    def test_page_offers_the_network_route_instead(self) -> None:
        """Reaching the app from a phone needs no flag any more, only the QR."""
        self.assertIn("Op je telefoon openen", PAGE_TEXT)
        self.assertIn("wifi", PAGE_TEXT)
        self.assertIn("python main.py --local-only", PAGE_TEXT, "de opt-out moet vindbaar blijven")

    def test_the_app_is_reachable_from_a_phone_without_a_restart(self) -> None:
        """Switching this on later needed Ctrl+C, which killed the app first.

        Streamlit fixes its bind address at startup, so no button can change it;
        binding to the network right away is what removes the restart.
        """
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("share_on_network: bool = True", source)
        self.assertIn('"--local-only"', source)
        self.assertIn('"--network"', source, "de oude vlag moet blijven werken")

    def test_readme_documents_the_phone_route(self) -> None:
        self.assertIn("--network", README_TEXT)


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
