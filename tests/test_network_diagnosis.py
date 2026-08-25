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


class AddressShapeTests(unittest.TestCase):
    """Every check on the laptop green, and the phone still gets nothing.

    That was the real situation on eduroam: a correct firewall rule, an app
    that listens, and a network that never lets the traffic through. The
    address is the only evidence of it available from this machine.
    """

    def test_an_address_in_your_own_network_is_fine(self) -> None:
        check = nd.check_address_shape("192.168.1.24")
        self.assertEqual(nd.OK, check.status)
        self.assertIn("192.168.1.24", check.detail)

    def test_a_public_address_is_reported_with_the_route_that_does_work(self) -> None:
        check = nd.check_address_shape("130.37.65.186")
        self.assertEqual(nd.PROBLEM, check.status)
        self.assertIn("publiek adres", check.detail)
        self.assertIn("hotspot", check.fix)

    def test_no_address_is_unknown_rather_than_a_verdict(self) -> None:
        self.assertEqual(nd.UNKNOWN, nd.check_address_shape(None).status)

    def _diagnose(self, address: str, firewall: list[nd.Check]) -> nd.Diagnosis:
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=firewall), \
             mock.patch.object(nd, "windows_firewall_command", return_value="New-NetFirewallRule ..."):
            return nd.diagnose(8501, address=address)

    def test_a_public_address_becomes_the_conclusion_when_the_laptop_is_fine(self) -> None:
        result = self._diagnose("130.37.65.186", [
            nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
            nd.Check("Firewallregel voor deze app", nd.OK, "aanwezig"),
        ])
        self.assertFalse(result.fixable_here)
        self.assertIn("publiek adres", result.conclusion)
        self.assertIn("hotspot", result.conclusion)

    def test_a_real_firewall_problem_still_outranks_the_address(self) -> None:
        """A missing rule is fixable here; the network is not. Fix first."""
        result = self._diagnose("130.37.65.186", [
            nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
            nd.Check("Firewallregel voor deze app", nd.PROBLEM, "ontbreekt"),
        ])
        self.assertTrue(result.fixable_here)
        self.assertIn("firewall", result.conclusion.lower())

    def test_a_hotspot_address_is_recognised_as_the_route_with_nothing_between(self) -> None:
        check = nd.check_address_shape("172.20.10.3")
        self.assertEqual(nd.OK, check.status)
        self.assertIn("iPhone", check.detail)

    def test_on_a_hotspot_client_isolation_is_not_offered_as_an_excuse(self) -> None:
        """Sending someone to the hotspot they are already on helps nobody."""
        result = self._diagnose("172.20.10.3", [
            nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
            nd.Check("Firewallregel voor deze app", nd.OK, "aanwezig"),
        ])
        self.assertNotIn("zet deze laptop op de hotspot", result.conclusion.lower())
        self.assertIn("al op een gedeelde telefoonverbinding", result.conclusion)
        self.assertIn("4G/5G", result.conclusion)

    def test_the_finding_sits_next_to_the_listening_check(self) -> None:
        result = self._diagnose("192.168.1.24", [])
        self.assertEqual("Soort netwerkadres", result.checks[1].name)

    def test_adding_the_check_did_not_swallow_the_firewall_findings(self) -> None:
        result = self._diagnose("192.168.1.24", [
            nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
            nd.Check("Firewallregel voor deze app", nd.PROBLEM, "ontbreekt"),
        ])
        self.assertTrue(result.fixable_here)


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


class OtherBlockerTests(unittest.TestCase):
    """Windows Firewall being fine does not mean nothing is blocking.

    The tester's laptop reported a correct, applying rule for the right profile
    and still nothing reached the phone — so the checks have to look past
    Windows' own firewall.
    """

    BASIC = (
        "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=True\n"
        "RULE=True\nRULEAPPLIES=True\nRULEPROFILES=Public\nBLOCKED=0\nADMIN=False\n"
    )

    def _diagnose(self, deep: str) -> nd.Diagnosis:
        def fake_run(command, timeout=6):
            return deep if "FirewallProduct" in command[-1] else self.BASIC

        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", fake_run), \
             mock.patch.object(nd, "check_listening",
                               return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")):
            return nd.diagnose(8501, address="192.168.1.61")

    def test_a_third_party_firewall_is_named(self) -> None:
        result = self._diagnose("FIREWALLPRODUCTS=Cisco Secure Endpoint\nBROADBLOCKS=0\nBROADNAMES=\n")
        finding = next(check for check in result.checks if check.name == "Andere beveiligingssoftware")
        self.assertEqual(nd.PROBLEM, finding.status)
        self.assertIn("Cisco Secure Endpoint", finding.detail)
        self.assertNotIn("BROADBLOCKS", finding.detail, "sleutels van andere regels horen niet in de naam")
        self.assertFalse(result.fixable_here, "een ander pakket kan de app niet zelf openzetten")

    def test_windows_own_firewall_is_not_reported_as_a_third_party(self) -> None:
        result = self._diagnose("FIREWALLPRODUCTS=\nBROADBLOCKS=0\nBROADNAMES=\n")
        self.assertNotIn("Andere beveiligingssoftware", [check.name for check in result.checks])

    def test_broad_block_rules_are_reported_with_their_names(self) -> None:
        result = self._diagnose("FIREWALLPRODUCTS=\nBROADBLOCKS=3\nBROADNAMES=Block inbound Public|Corp baseline\n")
        finding = next(check for check in result.checks if check.name == "Brede blokkeerregels")
        self.assertIn("Block inbound Public", finding.detail)
        self.assertIn("Corp baseline", finding.detail)
        self.assertIn("blokkeerregels", result.conclusion)

    def test_nothing_extra_found_points_at_the_network(self) -> None:
        result = self._diagnose("FIREWALLPRODUCTS=\nBROADBLOCKS=0\nBROADNAMES=\n")
        self.assertIn("clientisolatie", result.conclusion)
        self.assertIn("geen andere beveiligingssoftware", result.conclusion)

    def test_the_slow_round_is_skipped_when_windows_already_explains_it(self) -> None:
        """No point enumerating every rule when the cause is already known."""
        calls: list[str] = []

        def fake_run(command, timeout=6):
            calls.append(command[-1])
            return (
                "CATEGORY=Public\nPROFILE=Public\nFIREWALL=True\nALLOWINBOUND=True\n"
                "RULE=False\nRULEAPPLIES=False\nBLOCKED=0\n"
            )

        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", fake_run), \
             mock.patch.object(nd, "check_listening",
                               return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "windows_firewall_command", return_value="New-NetFirewallRule ..."):
            nd.diagnose(8501, address="192.168.1.61")
        self.assertFalse(any("FirewallProduct" in call for call in calls), calls)

    def test_a_silent_deep_probe_adds_nothing(self) -> None:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value=""):
            self.assertEqual([], nd.check_other_blockers(8501))

    def test_the_deep_probe_is_windows_only(self) -> None:
        with mock.patch.object(nd.sys, "platform", "linux"):
            self.assertEqual([], nd.check_other_blockers(8501))


class ListenerMatchesRuleTests(unittest.TestCase):
    """A rule is bound to one executable; the listener may be another.

    Create the rule from the system Python while the app runs from a virtual
    environment and the rule is valid, correct, and irrelevant.
    """

    def _check(self, output: str) -> list[nd.Check]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd.sys, "executable", r"C:\proj\.venv\Scripts\python.exe"), \
             mock.patch.object(nd, "_run", return_value=output):
            return nd.check_listener_matches_rule(8501)

    def test_a_rule_for_another_executable_is_flagged(self) -> None:
        checks = self._check(
            "LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\Python312\\python.exe\n"
            "RULEPROGRAMS=C:\\proj\\.venv\\Scripts\\python.exe\n"
        )
        finding = next(check for check in checks if check.name == "Programma achter de poort")
        self.assertEqual(nd.PROBLEM, finding.status)
        self.assertIn("Python312", finding.detail)
        self.assertIn(".venv", finding.detail, "beide kanten van het verschil horen erin te staan")

    def test_a_rule_for_the_listening_executable_passes(self) -> None:
        """Compare with the rule, never with sys.executable.

        After the fix the rule names the base interpreter while sys.executable
        is still the virtual environment. Comparing against sys.executable
        reports a mismatch that no amount of fixing can ever clear — which is
        exactly what a tester ran into.
        """
        checks = self._check(
            "LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\Python312\\python.exe\n"
            "RULEPROGRAMS=C:\\Python312\\python.exe\n"
        )
        finding = next(check for check in checks if check.name == "Programma achter de poort")
        self.assertEqual(nd.OK, finding.status)

    def test_the_comparison_ignores_case(self) -> None:
        """Windows paths differ in case between tools all the time."""
        checks = self._check(
            "LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\PY312\\PYTHON.EXE\n"
            "RULEPROGRAMS=c:\\py312\\python.exe\n"
        )
        finding = next(check for check in checks if check.name == "Programma achter de poort")
        self.assertEqual(nd.OK, finding.status)

    def test_a_rule_bound_to_no_program_covers_everything(self) -> None:
        checks = self._check(
            "LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\Py312\\python.exe\nRULEPROGRAMS=Any\n"
        )
        finding = next(check for check in checks if check.name == "Programma achter de poort")
        self.assertEqual(nd.OK, finding.status)

    def test_without_a_rule_there_is_no_verdict_to_give(self) -> None:
        """The missing-rule check covers that; two verdicts would contradict."""
        checks = self._check(
            "LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\Py312\\python.exe\nRULEPROGRAMS=\n"
        )
        self.assertNotIn("Programma achter de poort", [check.name for check in checks])

    def test_a_loopback_only_listener_is_flagged(self) -> None:
        checks = self._check("LISTENADDRESSES=127.0.0.1\nLISTENPATHS=\nRULEPROGRAMS=\n")
        finding = next(check for check in checks if check.name == "Luisteradres")
        self.assertEqual(nd.PROBLEM, finding.status)
        self.assertIn("--local-only", finding.fix)

    def test_binding_to_all_interfaces_is_not_flagged(self) -> None:
        checks = self._check("LISTENADDRESSES=0.0.0.0|::\nLISTENPATHS=\nRULEPROGRAMS=\n")
        self.assertNotIn("Luisteradres", [check.name for check in checks])

    def test_a_silent_probe_adds_nothing(self) -> None:
        self.assertEqual([], self._check(""))

    def test_a_mismatch_is_offered_as_fixable(self) -> None:
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[
                 nd.Check("Windows Firewall", nd.PROBLEM, "aan"),
                 nd.Check("Firewallregel voor deze app", nd.OK, "aanwezig"),
             ]), \
             mock.patch.object(nd, "check_listener_matches_rule", return_value=[
                 nd.Check("Programma achter de poort", nd.PROBLEM, "andere python.exe"),
             ]), \
             mock.patch.object(nd, "windows_firewall_command", return_value="Remove...; New..."):
            result = nd.diagnose(8501, address="192.168.1.61")
        self.assertTrue(result.fixable_here)
        self.assertIn("andere python.exe", result.conclusion)

    def test_finding_the_mismatch_skips_the_slower_round(self) -> None:
        """The cause is known; enumerating every firewall rule is just delay."""
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[nd.Check("Windows Firewall", nd.PROBLEM, "aan")]), \
             mock.patch.object(nd, "check_listener_matches_rule", return_value=[
                 nd.Check("Programma achter de poort", nd.PROBLEM, "andere python.exe"),
             ]), \
             mock.patch.object(nd, "check_other_blockers") as deep, \
             mock.patch.object(nd, "windows_firewall_command", return_value="x"):
            nd.diagnose(8501, address="192.168.1.61")
        deep.assert_not_called()


class ReportEncodingTests(unittest.TestCase):
    """PowerShell 5.1 writes a BOM; the success marker sits behind it.

    A tester saw "Windows weigerde de regel:" followed by the word OK — the
    rule had been created and I reported it as a failure, twice.
    """

    def _apply(self, reported: str, returncode: int = 0) -> tuple[bool, str]:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Public"), \
             mock.patch.object(nd, "_read_report", return_value=reported), \
             mock.patch.object(nd.subprocess, "run",
                               return_value=mock.MagicMock(returncode=returncode, stdout="", stderr="")):
            return nd.apply_windows_firewall_rule(8501)

    def test_a_marker_behind_a_bom_still_counts_as_success(self) -> None:
        succeeded, message = self._apply("\ufeffOK")
        self.assertTrue(succeeded, message)

    def test_a_plain_marker_counts_as_success(self) -> None:
        self.assertTrue(self._apply("OK")[0])

    def test_a_real_error_is_still_a_failure(self) -> None:
        succeeded, message = self._apply("\ufeffAccess is denied.", returncode=1)
        self.assertFalse(succeeded)
        self.assertIn("Access is denied", message)

    def test_the_bom_is_stripped_when_reading_the_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.txt"
            report.write_bytes("\ufeffOK\r\n".encode("utf-8"))
            self.assertEqual("OK", nd._read_report(str(report)))
            self.assertFalse(report.exists(), "het rapport hoort opgeruimd te worden")

    def test_the_elevated_script_writes_the_marker_without_a_bom(self) -> None:
        script = nd.elevation_script(8501, "python.exe", "Public", r"C:\T\r.txt")
        inner = base64.b64decode(script.split("'-EncodedCommand','")[1].split("'")[0]).decode("utf-16-le")
        self.assertIn("-Value 'OK' -Encoding ASCII", inner)


class RuleTargetsTheListenerTests(unittest.TestCase):
    """The rule must name the program that holds the port.

    On the tester's laptop the port was held by the base interpreter while
    sys.executable was the virtual environment's python.exe. Recreating the
    rule from sys.executable would have rebuilt the very rule that did nothing.
    """

    def test_the_listening_program_is_read_from_windows(self) -> None:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run",
                               return_value="LISTENADDRESSES=0.0.0.0\nLISTENPATHS=C:\\Py312\\python.exe\n"):
            self.assertEqual(r"C:\Py312\python.exe", nd.listening_program(8501))

    def test_no_listener_falls_back_rather_than_guessing_wrong(self) -> None:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd, "_run", return_value="LISTENADDRESSES=\nLISTENPATHS=\n"):
            self.assertIsNone(nd.listening_program(8501))

    def test_the_command_prefers_the_listening_program(self) -> None:
        with mock.patch.object(nd.sys, "platform", "win32"), \
             mock.patch.object(nd.sys, "executable", r"C:\proj\.venv\Scripts\python.exe"), \
             mock.patch.object(nd, "listening_program", return_value=r"C:\Py312\python.exe"):
            command = nd.windows_firewall_command(8501, profile="Public")
        self.assertIn(r'-Program "C:\Py312\python.exe"', command)
        self.assertNotIn(".venv", command)

    def test_the_mismatch_fix_names_the_listener_not_the_app(self) -> None:
        mismatch = nd.Check(
            "Programma achter de poort", nd.PROBLEM, "andere python.exe",
            program=r"C:\Py312\python.exe",
        )
        with mock.patch.object(nd, "check_listening", return_value=nd.Check("Luistert op het netwerk", nd.OK, "open")), \
             mock.patch.object(nd, "check_windows_firewall", return_value=[nd.Check("Windows Firewall", nd.PROBLEM, "aan")]), \
             mock.patch.object(nd, "check_listener_matches_rule", return_value=[mismatch]), \
             mock.patch.object(nd, "current_firewall_profile", return_value="Public"), \
             mock.patch.object(nd.sys, "executable", r"C:\proj\.venv\Scripts\python.exe"):
            result = nd.diagnose(8501, address="192.168.1.61")
        self.assertTrue(result.fixable_here)
        self.assertIn(r"C:\Py312\python.exe", result.fix_command)
        self.assertNotIn(".venv", result.fix_command)


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
