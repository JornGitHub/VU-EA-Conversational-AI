from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

import main
from src.llm import ollama_setup


READY_REPORT = ollama_setup.OllamaSetupReport(cli_installed=True, server_running=True)


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
        with patch("sys.argv", ["main.py", *argv]), \
             contextlib.redirect_stdout(io.StringIO()):
            return main.parse_args()

    def test_default_run_installs_models_indexes_and_starts_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=ollama_setup.OllamaSetupReport(cli_installed=True, server_running=True)) as ollama, \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_called_once()
        ollama.assert_called_once()
        embeddings.assert_called_once()
        streamlit.assert_called_once()

    def test_embedding_build_is_skipped_when_ollama_is_unavailable(self) -> None:
        report = ollama_setup.OllamaSetupReport(cli_installed=False, server_running=False)
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=report), \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "run_streamlit", return_value=0), \
             patch("sys.argv", ["main.py"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            main.main()

        self.assertFalse(embeddings.call_args.kwargs["ollama_available"])

    def test_build_embeddings_flag_forces_a_rebuild_without_starting_the_app(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=ollama_setup.OllamaSetupReport(cli_installed=True, server_running=True)), \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--build-embeddings", "--skip-install"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            main.main()

        self.assertTrue(embeddings.call_args.kwargs["force"])
        streamlit.assert_not_called()

    def test_benchmark_flag_runs_the_benchmark_only(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "run_benchmark", return_value=0) as benchmark, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--benchmark", "--skip-install"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            main.main()

        benchmark.assert_called_once()
        ollama.assert_not_called()
        embeddings.assert_not_called()
        streamlit.assert_not_called()

    def test_skip_embeddings_leaves_the_index_alone(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=ollama_setup.OllamaSetupReport(cli_installed=True, server_running=True)), \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "run_streamlit", return_value=0), \
             patch("sys.argv", ["main.py", "--skip-embeddings"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            main.main()

        embeddings.assert_not_called()

    def test_embedding_model_is_pulled_alongside_the_chat_model(self) -> None:
        args = self.parse([])
        self.assertIn(ollama_setup.DEFAULT_EMBED_MODEL, main.selected_models(args))
        self.assertIn(ollama_setup.DEFAULT_OLLAMA_MODEL, main.selected_models(args))

    def test_skip_embeddings_drops_the_embedding_model_from_the_pull_list(self) -> None:
        args = self.parse(["--skip-embeddings"])
        self.assertNotIn(ollama_setup.DEFAULT_EMBED_MODEL, main.selected_models(args))

    def test_tests_run_does_not_download_models_or_start_app(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_embeddings", return_value=0) as embeddings, \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "run_unit_tests", return_value=0) as tests, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--tests"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(0, status)
        tests.assert_called_once()
        ollama.assert_not_called()
        embeddings.assert_not_called()
        streamlit.assert_not_called()

    def test_skip_flags_disable_setup_steps(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "setup_embeddings", return_value=0), \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--skip-install", "--skip-models"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_not_called()
        ollama.assert_not_called()
        streamlit.assert_called_once()

    def test_setup_only_does_not_start_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=0) as install, \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "setup_embeddings", return_value=0), \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--setup"]), \
             contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(0, status)
        install.assert_called_once()
        ollama.assert_called_once()
        streamlit.assert_not_called()

    def test_failed_install_stops_before_streamlit(self) -> None:
        with patch.object(main, "install_requirements", return_value=1), \
             patch.object(main, "setup_embeddings", return_value=0), \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(1, status)
        ollama.assert_not_called()
        streamlit.assert_not_called()

    def test_llm_query_prepares_models(self) -> None:
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_embeddings", return_value=0), \
             patch.object(main, "setup_ollama", return_value=READY_REPORT) as ollama, \
             patch.object(main, "run_query", return_value=0) as query, \
             patch.object(main, "run_streamlit", return_value=0) as streamlit, \
             patch("sys.argv", ["main.py", "--query", "wat is instroom?", "--llm"]), \
                  contextlib.redirect_stdout(io.StringIO()):
            status = main.main()

        self.assertEqual(0, status)
        ollama.assert_called_once()
        query.assert_called_once()
        streamlit.assert_not_called()

    def test_check_run_ends_with_a_summary_and_points_to_the_app(self) -> None:
        buffer = io.StringIO()
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "run_unit_tests", return_value=0), \
             patch.object(main, "run_streamlit", return_value=0), \
             patch("sys.argv", ["main.py", "--tests", "--skip-install"]), \
             contextlib.redirect_stdout(buffer):
            main.main()

        output = buffer.getvalue()
        self.assertIn("Samenvatting", output)
        self.assertIn("Unit tests", output)
        self.assertIn("starten de app niet", output)
        self.assertIn("python main.py", output)

    def test_app_run_does_not_claim_that_nothing_started(self) -> None:
        buffer = io.StringIO()
        with patch.object(main, "install_requirements", return_value=0), \
             patch.object(main, "setup_ollama", return_value=READY_REPORT), \
             patch.object(main, "setup_embeddings", return_value=0), \
             patch.object(main, "run_streamlit", return_value=0), \
             patch("sys.argv", ["main.py"]), \
             contextlib.redirect_stdout(buffer):
            main.main()

        self.assertNotIn("starten de app niet", buffer.getvalue())

    def test_status_markers_fall_back_to_ascii_on_a_legacy_console(self) -> None:
        # Windows consoles and redirected output often cannot encode check marks.
        self.assertTrue(main.console_supports("abc"))
        with patch.object(main.sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252")):
            self.assertFalse(main.console_supports("✓✗"))

    def test_model_flag_selects_that_chat_model(self) -> None:
        args = self.parse(["--model", "qwen3:4b"])
        self.assertEqual("qwen3:4b", main.selected_models(args)[0])

    def test_model_flag_with_skip_embeddings_selects_only_that_model(self) -> None:
        args = self.parse(["--model", "qwen3:4b", "--skip-embeddings"])
        self.assertEqual(["qwen3:4b"], main.selected_models(args))

    def test_default_models_come_from_setup_module(self) -> None:
        args = self.parse([])
        self.assertEqual(list(ollama_setup.REQUIRED_OLLAMA_MODELS), main.selected_models(args))


if __name__ == "__main__":
    unittest.main()
