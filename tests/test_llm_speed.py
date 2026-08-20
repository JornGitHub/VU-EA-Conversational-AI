"""Tests for the settings that decide how long a local model makes you wait."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.llm.ollama_client import (
    DEFAULT_KEEP_ALIVE,
    DEFAULT_OPTIONS,
    build_payload,
    generate_with_ollama,
    stream_with_ollama,
    warm_up,
)


def json_response(payload: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = ""
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def stream_response(lines: list[str], status: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.__enter__ = lambda _self: response
    response.__exit__ = lambda *_args: False
    response.iter_lines.return_value = lines
    response.raise_for_status.return_value = None
    return response


class PayloadTests(unittest.TestCase):
    def test_thinking_is_disabled_by_default(self) -> None:
        """Qwen3 puts reasoning in message.thinking, which never reaches the UI."""
        payload = build_payload("prompt", "qwen3:8b", stream=True)
        self.assertIs(False, payload["think"])

    def test_generation_is_bounded_and_the_model_stays_loaded(self) -> None:
        payload = build_payload("prompt", "qwen3:8b", stream=False)
        self.assertEqual(DEFAULT_KEEP_ALIVE, payload["keep_alive"])
        self.assertEqual(DEFAULT_OPTIONS["num_predict"], payload["options"]["num_predict"])
        self.assertEqual(DEFAULT_OPTIONS["num_ctx"], payload["options"]["num_ctx"])
        self.assertLessEqual(payload["options"]["num_predict"], 600)

    def test_caller_options_win(self) -> None:
        payload = build_payload("prompt", "qwen3:8b", stream=False, options={"num_predict": 1})
        self.assertEqual(1, payload["options"]["num_predict"])
        self.assertEqual(DEFAULT_OPTIONS["temperature"], payload["options"]["temperature"])

    def test_think_can_be_omitted(self) -> None:
        self.assertNotIn("think", build_payload("prompt", "model", stream=False, think=None))


class ThinkFallbackTests(unittest.TestCase):
    def test_generate_retries_without_think_when_the_server_rejects_it(self) -> None:
        rejection = json_response({}, status=400)
        rejection.text = "unknown field \"think\""
        accepted = json_response({"message": {"content": "antwoord"}})

        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.side_effect = [rejection, accepted]
            self.assertEqual("antwoord", generate_with_ollama("prompt", model="llama3"))
            second_payload = session.return_value.post.call_args_list[1].kwargs["json"]
        self.assertNotIn("think", second_payload)

    def test_stream_retries_without_think_when_the_server_rejects_it(self) -> None:
        rejection = stream_response([], status=400, text="think is not supported")
        accepted = stream_response(['{"message": {"content": "ok"}, "done": true}'])

        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.side_effect = [rejection, accepted]
            self.assertEqual(["ok"], list(stream_with_ollama("prompt", model="llama3")))

    def test_other_400_errors_are_not_retried(self) -> None:
        import requests

        failure = json_response({}, status=400)
        failure.text = "model not found"
        failure.raise_for_status.side_effect = requests.exceptions.HTTPError(response=failure)

        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.return_value = failure
            with self.assertRaises(RuntimeError) as raised:
                generate_with_ollama("prompt", model="ontbrekend")
        self.assertIn("ollama pull ontbrekend", str(raised.exception))
        self.assertEqual(1, session.return_value.post.call_count)


class WarmUpTests(unittest.TestCase):
    def test_warm_up_loads_the_model_without_generating(self) -> None:
        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.return_value = json_response({"message": {"content": ""}})
            self.assertTrue(warm_up("qwen3:8b"))
            payload = session.return_value.post.call_args.kwargs["json"]
        self.assertEqual(1, payload["options"]["num_predict"])
        self.assertFalse(payload["stream"])

    def test_warm_up_reports_failure_instead_of_raising(self) -> None:
        import requests

        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.side_effect = requests.exceptions.ConnectionError("down")
            self.assertFalse(warm_up("qwen3:8b"))


class StreamingContentTests(unittest.TestCase):
    def test_thinking_fragments_are_not_shown_as_answer_text(self) -> None:
        lines = [
            '{"message": {"thinking": "laat me nadenken"}, "done": false}',
            '{"message": {"content": "Het antwoord."}, "done": true}',
        ]
        with patch("src.llm.ollama_client._session") as session:
            session.return_value.post.return_value = stream_response(lines)
            self.assertEqual(["Het antwoord."], list(stream_with_ollama("prompt")))


if __name__ == "__main__":
    unittest.main()
