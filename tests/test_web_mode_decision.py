import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.definitions.search import should_attempt_web


class WebModeDecisionTests(unittest.TestCase):
    def test_fallback_sufficient_skips_web(self):
        attempted, reason = should_attempt_web("fallback", True, [], "medium")
        self.assertIs(attempted, False)
        self.assertEqual(reason, "local_context_sufficient")

    def test_force_sufficient_attempts_web(self):
        attempted, reason = should_attempt_web("force", True, [], "medium")
        self.assertIs(attempted, True)
        self.assertNotEqual(reason, "local_context_sufficient")

    def test_enhance_sufficient_attempts_web(self):
        attempted, reason = should_attempt_web("enhance", True, [], "medium")
        self.assertIs(attempted, True)
        self.assertNotEqual(reason, "local_context_sufficient")

    def test_off_disables_web(self):
        attempted, reason = should_attempt_web("off", True, [], "low")
        self.assertIs(attempted, False)
        self.assertEqual(reason, "web_disabled")


if __name__ == "__main__":
    unittest.main()
