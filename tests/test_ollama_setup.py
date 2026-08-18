from __future__ import annotations

import unittest
from unittest.mock import patch

import main
from src.llm import ollama_setup


class ModelMatchingTests(unittest.TestCase):
    def test_exact_tag_match(self) -> None:
        self.assertTrue(ollama_setup.model_is_installed("qwen3:8b", ["qwen3:8b", "llama3:8b"]))

    def test_untagged_name_matches_latest(self) -> None:
        self.assertTrue(ollama_setup.model_is_installed("qwen3", ["qwen3:latest"]))

    def test_other_tag_does_not_match(self) -> None:
        self.assertFalse(ollama_setup.model_is_installed("qwen3:8b", ["qwen3:30b"]))

    def test_empty_name_never_matches(self) -> None:
        self.assertFalse(ollama_setup.model_is_installed("  ", ["qwen3:8b"]))


class EnsureModelsTests(unittest.TestCase):
    def test_missing_cli_reports_install_hint_without_raising(self) -> None:
        with patch.object(ollama_setup, "is_ollama_installed", return_value=False):
            report = ollama_setup.ensure_models(["qwen3:8b"], printer=lambda _: None)

        self.assertFalse(report.cli_installed)
        self.assertFalse(report.llm_available)
        self.assertTrue(any("ollama.com/download" in message for message in report.messages))
        self.assertEqual([], report.models_failed)

    def test_unreachable_server_is_reported_as_warning(self) -> None:
        with patch.object(ollama_setup, "is_ollama_installed", return_value=True), \
             patch.object(ollama_setup, "is_server_running", return_value=False), \
             patch.object(ollama_setup, "start_server", return_value=False):
            report = ollama_setup.ensure_models(["qwen3:8b"], printer=lambda _: None)

        self.assertTrue(report.cli_installed)
        self.assertFalse(report.server_running)
        self.assertTrue(any("ollama serve" in message for message in report.messages))

    def test_present_model_is_not_pulled_again(self) -> None:
        with patch.object(ollama_setup, "is_ollama_installed", return_value=True), \
             patch.object(ollama_setup, "is_server_running", return_value=True), \
             patch.object(ollama_setup, "list_installed_models", return_value=["qwen3:8b"]), \
             patch.object(ollama_setup, "pull_model") as pull:
            report = ollama_setup.ensure_models(["qwen3:8b"], printer=lambda _: None)

        pull.assert_not_called()
        self.assertEqual(["qwen3:8b"], report.models_present)
        self.assertTrue(report.llm_available)

    def test_missing_model_is_pulled(self) -> None:
        with patch.object(ollama_setup, "is_ollama_installed", return_value=True), \
             patch.object(ollama_setup, "is_server_running", return_value=True), \
             patch.object(ollama_setup, "list_installed_models", return_value=[]), \
             patch.object(ollama_setup, "pull_model", return_value=True) as pull:
            report = ollama_setup.ensure_models(["qwen3:8b"], printer=lambda _: None)

        pull.assert_called_once()
        self.assertEqual(["qwen3:8b"], report.models_pulled)
        self.assertTrue(report.llm_available)

    def test_failed_pull_is_reported_without_raising(self) -> None:
        with patch.object(ollama_setup, "is_ollama_installed", return_value=True), \
             patch.object(ollama_setup, "is_server_running", return_value=True), \
             patch.object(ollama_setup, "list_installed_models", return_value=[]), \
             patch.object(ollama_setup, "pull_model", return_value=False):
            report = ollama_setup.ensure_models(["qwen3:8b"], printer=lambda _: None)

        self.assertEqual(["qwen3:8b"], report.models_failed)
        self.assertFalse(report.llm_available)
        self.assertIn("qwen3:8b", report.summary())


class RunnerFlowTests(unittest.TestCase):
    def parse(self, argv: list[str]):
        with patch("sys.argv", ["main.py", *argv]):
            return main.parse_args()

    def test_default_run_installs_models_and_starts_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py"]):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_called_once()
        ollama.assert_called_once()
        streamlit.assert_called_once()

    def test_tests_run_does_not_download_models_or_start_app(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_unit_tests", return_value=0) as tests, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--tests"]):
            status = main.main()

        self.assertEqual(0, status)
        tests.assert_called_once()
        ollama.assert_not_called()
        streamlit.assert_not_called()

    def test_skip_flags_disable_setup_steps(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--skip-install", "--skip-models"]):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_not_called()
        ollama.assert_not_called()
        streamlit.assert_called_once()

    def test_setup_only_does_not_start_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--setup"]):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_called_once()
        ollama.assert_called_once()
        streamlit.assert_not_called()

    def test_failed_install_stops_before_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=1), \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py"]):
            status = main.main()

        self.assertEqual(1, status)
        ollama.assert_not_called()
        streamlit.assert_not_called()

    def test_llm_query_prepares_models(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=0) as ollama, \
             patch.object(main, "run_query", return_value=0) as query, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--query", "wat is instroom?", "--llm"]):
            status = main.main()

        self.assertEqual(0, status)
        ollama.assert_called_once()
        query.assert_called_once()
        streamlit.assert_not_called()

    def test_model_flag_selects_single_model(self) -> None:
        args = self.parse(["--model", "qwen3:4b"])
        self.assertEqual(["qwen3:4b"], main.selected_models(args))

    def test_default_models_come_from_setup_module(self) -> None:
        args = self.parse([])
        self.assertEqual(list(ollama_setup.REQUIRED_OLLAMA_MODELS), main.selected_models(args))


if __name__ == "__main__":
    unittest.main()
