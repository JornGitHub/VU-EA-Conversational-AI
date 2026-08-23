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

    def test_a_rule_that_applies_here_clears_the_firewall(self) -> None:
        checks = self._probe(
            "CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=True\nRULEAPPLIES=True\n"
            "RULEPROFILES=Private\n"
        )
        by_name = {check.name: check for check in checks}
        self.assertEqual(nd.OK, by_name["Firewallregel voor deze app"].status)

    def test_a_rule_we_cannot_confirm_applies_is_not_called_ok(self) -> None:
        """Reporting OK for a rule doing nothing is worse than reporting nothing."""
        checks = self._probe("CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=True\n")
        by_name = {check.name: check for check in checks}
        self.assertEqual(nd.PROBLEM, by_name["Firewallregel voor deze app"].status)

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

    def test_success_is_reported_on_a_zero_exit_with_confirmation(self) -> None:
        completed = mock.MagicMock(returncode=0, stdout="", stderr="")
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Public"), \
             mock.patch.object(nd, "_read_report", return_value="OK"), \
             mock.patch.object(nd.subprocess, "run", return_value=completed):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertTrue(succeeded)
        self.assertIn("Public", message)


class ElevationFailureTests(unittest.TestCase):
    """The elevated window closes itself, so its error must be captured.

    A tester saw the rule fail and PowerShell disappear before the message
    could be read — which was the one piece of information that mattered.
    """

    def test_the_inner_script_writes_its_error_to_a_file(self) -> None:
        script = nd.elevation_script(8501, "python.exe", "Private", r"C:\Temp\r.txt")
        encoded = script.split("'-EncodedCommand','")[1].split("'")[0]
        inner = base64.b64decode(encoded).decode("utf-16-le")
        self.assertIn("Set-Content", inner)
        self.assertIn("$_.Exception.Message", inner)
        self.assertIn("'OK'", inner)

    def test_a_refused_elevation_is_told_apart_from_a_refused_rule(self) -> None:
        """No report file means the elevated shell never ran at all."""
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Private"), \
             mock.patch.object(nd, "_read_report", return_value=""), \
             mock.patch.object(nd.subprocess, "run", return_value=mock.MagicMock(returncode=2, stdout="", stderr="")):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertFalse(succeeded)
        self.assertIn("niet geopend", message)

    def test_windows_own_error_is_passed_through(self) -> None:
        windows_error = "Cannot create a file when that file already exists."
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Private"), \
             mock.patch.object(nd, "_read_report", return_value=windows_error), \
             mock.patch.object(nd.subprocess, "run", return_value=mock.MagicMock(returncode=1, stdout="", stderr="")):
            succeeded, message = nd.apply_windows_firewall_rule(8501)
        self.assertFalse(succeeded)
        self.assertIn(windows_error, message)
        self.assertIn("group policy", message.lower())

    def test_success_needs_both_a_zero_exit_and_the_ok_marker(self) -> None:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Private"), \
             mock.patch.object(nd, "_read_report", return_value=""), \
             mock.patch.object(nd.subprocess, "run", return_value=mock.MagicMock(returncode=0, stdout="", stderr="")):
            succeeded, _ = nd.apply_windows_firewall_rule(8501)
        self.assertFalse(succeeded, "exitcode 0 zonder bevestiging is geen succes")

    def test_the_it_request_carries_everything_needed(self) -> None:
        text = nd.it_request_text(8501, r"C:\Python312\python.exe")
        self.assertIn("8501", text)
        self.assertIn(r"C:\Python312\python.exe", text)
        self.assertIn("New-NetFirewallRule", text)


class BlockRuleTests(unittest.TestCase):
    """A Block rule beats an Allow rule in Windows Firewall, always."""

    def _probe(self, output: str) -> list[nd.Check]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value=output):
            return nd.check_windows_firewall(8501)

    def test_existing_block_rules_are_reported(self) -> None:
        checks = self._probe(
            "CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=False\nBLOCKED=2\nADMIN=False\n"
        )
        names = [check.name for check in checks]
        self.assertIn("Blokkeerregel voor Python", names)
        blocker = next(check for check in checks if check.name == "Blokkeerregel voor Python")
        self.assertEqual(nd.PROBLEM, blocker.status)
        self.assertIn("Remove-NetFirewallRule", blocker.fix)

    def test_no_block_rules_means_no_such_check(self) -> None:
        checks = self._probe("CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=False\nBLOCKED=0\n")
        self.assertNotIn("Blokkeerregel voor Python", [check.name for check in checks])

    def test_a_block_rule_outranks_the_missing_allow_rule(self) -> None:
        """Adding an Allow rule would change nothing while a Block rule stands."""
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[
                 nd.Check("Blokkeerregel voor Python", nd.PROBLEM, "twee stuks"),
                 nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                 nd.Check("Firewallregel voor deze app", nd.PROBLEM, "ontbreekt"),
             ]):
            result = nd.diagnose(8501, address="192.168.1.24")
        self.assertIn("blokkeerregel", result.conclusion.lower())
        self.assertFalse(result.fixable_here, "eerst blokkeerregel weg, anders helpt toevoegen niets")

    def test_missing_admin_rights_are_flagged_before_trying(self) -> None:
        checks = self._probe("CATEGORY=Private\nPROFILE=Private\nFIREWALL=True\nRULE=False\nBLOCKED=0\nADMIN=False\n")
        self.assertIn("Beheerdersrechten", [check.name for check in checks])


class RuleAppliesTests(unittest.TestCase):
    """A rule that exists is not a rule that applies.

    The tester's laptop had a rule named exactly right while the phone still
    could not connect: the network is Public and the rule was scoped Private.
    Checking only for the name reported "OK" for a rule doing nothing.
    """

    def _probe(self, output: str) -> list[nd.Check]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value=output):
            return nd.check_windows_firewall(8501)

    def test_a_rule_for_another_profile_is_a_problem_not_an_ok(self) -> None:
        checks = self._probe(
            "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=True\n"
            "RULE=True\nRULEAPPLIES=False\nRULEPROFILES=Private\nBLOCKED=0\n"
        )
        rule = next(check for check in checks if check.name == "Firewallregel voor deze app")
        self.assertEqual(nd.PROBLEM, rule.status)
        self.assertIn("Private", rule.detail)
        self.assertIn("Public", rule.detail)

    def test_a_rule_for_this_profile_is_ok(self) -> None:
        checks = self._probe(
            "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=True\n"
            "RULE=True\nRULEAPPLIES=True\nRULEPROFILES=Public\nBLOCKED=0\n"
        )
        rule = next(check for check in checks if check.name == "Firewallregel voor deze app")
        self.assertEqual(nd.OK, rule.status)

    def test_a_wrong_profile_rule_is_offered_as_fixable(self) -> None:
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[
                 nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                 nd.Check("Firewallregel voor deze app", nd.PROBLEM,
                          "Er is een regel 'X', maar die geldt voor Private en dit netwerk is 'Public'."),
             ]), \
             mock.patch.object(nd, "windows_firewall_command", return_value="Remove...; New..."):
            result = nd.diagnose(8501, address="192.168.1.61")
        self.assertTrue(result.fixable_here)
        self.assertIn("ander netwerkprofiel", result.conclusion)

    def test_the_fix_replaces_rather_than_stacks(self) -> None:
        """Leaving the old rule beside the new one changes nothing."""
        command = nd.windows_firewall_command(8501, "python.exe", "Public")
        self.assertIn("Remove-NetFirewallRule", command)
        self.assertLess(command.index("Remove-NetFirewallRule"), command.index("New-NetFirewallRule"))


class PolicyTests(unittest.TestCase):
    """Group policy can make the whole firewall route pointless."""

    def _probe(self, output: str) -> list[nd.Check]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value=output):
            return nd.check_windows_firewall(8501)

    def test_ignored_inbound_rules_are_reported(self) -> None:
        checks = self._probe(
            "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=False\n"
            "RULE=True\nRULEAPPLIES=True\nRULEPROFILES=Public\nBLOCKED=0\n"
        )
        self.assertIn("Inkomende regels toegestaan", [check.name for check in checks])

    def test_not_configured_is_not_treated_as_blocked(self) -> None:
        """NotConfigured means the default applies, which allows the rules."""
        checks = self._probe(
            "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=NotConfigured\n"
            "RULE=True\nRULEAPPLIES=True\nRULEPROFILES=Public\nBLOCKED=0\n"
        )
        self.assertNotIn("Inkomende regels toegestaan", [check.name for check in checks])

    def test_policy_verdict_stops_offering_a_fix_that_cannot_work(self) -> None:
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[
                 nd.Check("Inkomende regels toegestaan", nd.PROBLEM, "beleid negeert ze"),
                 nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                 nd.Check("Firewallregel voor deze app", nd.OK, "aanwezig"),
             ]):
            result = nd.diagnose(8501, address="192.168.1.61")
        self.assertFalse(result.fixable_here)
        self.assertIn("hotspot", result.conclusion)
        self.assertIn("zoek.html", result.conclusion, "wie alleen wil opzoeken heeft een route zonder netwerk")


class SafetyTests(unittest.TestCase):
    def test_a_failing_system_command_never_raises(self) -> None:
        with mock.patch.object(nd.subprocess, "run", side_effect=OSError("geen powershell")):
            self.assertEqual("", nd._run(["powershell"]))

    def test_diagnosis_never_reaches_outside_this_machine(self) -> None:
        """Everything here is local; a diagnosis must not phone home.

        A URL inside a message is fine — that is advice, not a request. What
        must not appear is a way to make one.
        """
        import ast

        tree = ast.parse(Path(nd.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("urllib", "requests", "http", "httpx", "ftplib", "smtplib"):
            self.assertNotIn(forbidden, imported, f"{forbidden} hoort hier niet")

    def test_the_only_connection_made_is_to_this_machine(self) -> None:
        """The one socket we open goes to our own address, to test listening."""
        with mock.patch.object(nd.socket, "create_connection") as connect:
            nd.check_listening("192.168.1.61", 8501)
        connect.assert_called_once()
        self.assertEqual(("192.168.1.61", 8501), connect.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
