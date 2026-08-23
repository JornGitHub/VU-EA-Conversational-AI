"""Guard the network diagnosis: a wrong verdict sends someone the wrong way.

The symptom (page loads, screen stays blank, then a timeout) has several
causes that look identical from the other device. These tests pin which
evidence leads to which conclusion, and that the Windows commands we generate
are exactly as narrow as they claim to be.
"""

from __future__ import annotations

import base64
import unittest
from pathlib import Path
from unittest import mock

from src import network_diagnosis as nd


class ListeningCheckTests(unittest.TestCase):
    def test_a_closed_port_is_reported_as_not_listening(self) -> None:
        with mock.patch.object(nd.socket, "create_connection", side_effect=ConnectionRefusedError):
            check = nd.check_listening("192.168.1.24", 8501)
        self.assertEqual(nd.PROBLEM, check.status)
        self.assertIn("--local-only", check.fix)

    def test_an_open_port_is_reported_as_listening(self) -> None:
        with mock.patch.object(nd.socket, "create_connection", mock.MagicMock()):
            check = nd.check_listening("192.168.1.24", 8501)
        self.assertEqual(nd.OK, check.status)

    def test_no_address_is_unknown_rather_than_a_verdict(self) -> None:
        check = nd.check_listening(None, 8501)
        self.assertEqual(nd.UNKNOWN, check.status)


class WindowsProbeTests(unittest.TestCase):
    """netsh output is translated on a Dutch Windows; these cmdlets are not."""

    def _probe(self, output: str) -> list[nd.Check]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value=output):
            return nd.check_windows_firewall(8501)

    def test_firewall_on_without_a_rule_is_the_problem(self) -> None:
        checks = self._probe("CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=False\n")
        by_name = {check.name: check for check in checks}
        self.assertEqual(nd.PROBLEM, by_name["Windows Firewall"].status)
        self.assertEqual(nd.PROBLEM, by_name["Firewallregel voor deze app"].status)

    def test_an_existing_rule_clears_the_firewall(self) -> None:
        checks = self._probe("CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=True\n")
        by_name = {check.name: check for check in checks}
        self.assertEqual(nd.OK, by_name["Firewallregel voor deze app"].status)

    def test_a_public_network_is_reported_because_it_changes_the_fix(self) -> None:
        """A rule scoped to Private does nothing on a network Windows calls Public."""
        checks = self._probe("CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nRULE=False\n")
        detail = next(check.detail for check in checks if check.name == "Netwerkprofiel")
        self.assertIn("Public", detail)

    def test_an_unreadable_firewall_is_unknown_not_fine(self) -> None:
        checks = self._probe("")
        self.assertEqual([nd.UNKNOWN], [check.status for check in checks])

    def test_nothing_is_reported_off_windows(self) -> None:
        with mock.patch.object(nd.sys, "platform", "linux"):
            self.assertEqual([], nd.check_windows_firewall(8501))


class ConclusionTests(unittest.TestCase):
    def _diagnose(self, listening: nd.Check, firewall: list[nd.Check]) -> nd.Diagnosis:
        with mock.patch.object(nd, "check_listening", return_value=listening), \
             mock.patch.object(nd, "check_windows_firewall", return_value=firewall), \
             mock.patch.object(nd, "windows_firewall_command", return_value="New-NetFirewallRule ..."):
            return nd.diagnose(8501, address="192.168.1.24")

    def test_not_listening_outranks_everything_else(self) -> None:
        result = self._diagnose(nd.Check("Luistert op het netwerk", nd.PROBLEM, "dicht"), [])
        self.assertIn("luistert niet", result.conclusion)
        self.assertFalse(result.fixable_here)

    def test_firewall_without_a_rule_is_offered_as_fixable(self) -> None:
        result = self._diagnose(
            nd.Check("Luistert op het netwerk", nd.OK, "open"),
            [
                nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                nd.Check("Firewallregel voor deze app", nd.PROBLEM, "ontbreekt"),
            ],
        )
        self.assertTrue(result.fixable_here)
        self.assertIn("firewall", result.conclusion.lower())

    def test_an_allowed_firewall_points_at_the_network_instead(self) -> None:
        """Two different devices failing means it is not the devices."""
        result = self._diagnose(
            nd.Check("Luistert op het netwerk", nd.OK, "open"),
            [
                nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                nd.Check("Firewallregel voor deze app", nd.OK, "aanwezig"),
            ],
        )
        self.assertFalse(result.fixable_here)
        self.assertIn("clientisolatie", result.conclusion)

    def test_off_windows_names_both_remaining_causes(self) -> None:
        result = self._diagnose(nd.Check("Luistert op het netwerk", nd.OK, "open"), [])
        self.assertIn("firewall", result.conclusion.lower())
        self.assertIn("clientisolatie", result.conclusion)

    def test_the_report_survives_json(self) -> None:
        """The UI stores it in session state between reruns."""
        import json

        result = self._diagnose(nd.Check("Luistert op het netwerk", nd.OK, "open"), [])
        self.assertEqual(result.conclusion, json.loads(json.dumps(result.as_dict()))["conclusion"])


class WindowsCommandTests(unittest.TestCase):
    def test_the_rule_is_as_narrow_as_it_claims(self) -> None:
        command = nd.windows_firewall_command(8501, r"C:\\Python312\\python.exe", "Private")
        self.assertIn("-Direction Inbound", command)
        self.assertIn("-Protocol TCP", command)
        self.assertIn("-LocalPort 8501", command)
        self.assertIn("-Profile Private", command)
        self.assertIn(r"C:\\Python312\\python.exe", command)
        self.assertNotIn("-Profile Any", command)

    def test_the_rule_follows_the_network_windows_is_actually_on(self) -> None:
        command = nd.windows_firewall_command(8501, "python.exe", "Public")
        self.assertIn("-Profile Public", command)

    def test_the_elevated_command_is_encoded_not_quoted(self) -> None:
        """Quoting a command with spaces through Start-Process silently mangles it."""
        script = nd.elevation_script(8501, r"C:\\Program Files\\Python312\\python.exe", "Private")
        self.assertIn("-EncodedCommand", script)
        self.assertIn("-Verb RunAs", script)
        self.assertIn("exit $p.ExitCode", script, "een geweigerde UAC-vraag moet zichtbaar falen")

        encoded = script.split("'-EncodedCommand','")[1].split("'")[0]
        decoded = base64.b64decode(encoded).decode("utf-16-le")
        self.assertIn("New-NetFirewallRule", decoded)
        self.assertIn(r"C:\\Program Files\\Python312\\python.exe", decoded)
        self.assertIn("exit 1", decoded, "een mislukte regel moet een exitcode geven")

    def test_applying_is_refused_off_windows(self) -> None:
        with mock.patch.object(nd.sys, "platform", "linux"):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertFalse(succeeded)
        self.assertIn("Windows", message)

    def test_a_refused_uac_prompt_is_reported_as_failure(self) -> None:
        completed = mock.MagicMock(returncode=1, stdout="", stderr="")
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Private"), \
             mock.patch.object(nd.subprocess, "run", return_value=completed):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertFalse(succeeded)
        self.assertIn("beheerdersrechten", message)

    def test_success_is_reported_only_on_a_zero_exit(self) -> None:
        completed = mock.MagicMock(returncode=0, stdout="", stderr="")
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Public"), \
             mock.patch.object(nd.subprocess, "run", return_value=completed):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertTrue(succeeded)
        self.assertIn("Public", message)


class SafetyTests(unittest.TestCase):
    def test_a_failing_system_command_never_raises(self) -> None:
        with mock.patch.object(nd.subprocess, "run", side_effect=OSError("geen powershell")):
            self.assertEqual("", nd._run(["powershell"]))

    def test_diagnosis_never_reaches_outside_this_machine(self) -> None:
        """Everything here is local; a diagnosis must not phone home."""
        text = Path(nd.__file__).read_text(encoding="utf-8")
        for forbidden in ("http://", "https://", "urllib", "requests"):
            self.assertNotIn(forbidden, text, f"{forbidden} hoort hier niet")


if __name__ == "__main__":
    unittest.main()
