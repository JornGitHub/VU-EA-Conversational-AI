"""Find out why another device cannot reach this app, and offer to fix it.

The symptom is always the same — the page loads, then the screen stays blank
until the browser gives up — and there are only a handful of causes. Guessing
between them costs a colleague an afternoon, so this checks the ones that can
be checked and says plainly which ones cannot.

What can be established from this machine:

* whether the server actually listens on the network interface, not just on
  loopback;
* whether this machine can reach its own network address (so the socket is
  really open there);
* on Windows, whether the firewall is on and whether an inbound rule exists
  for this Python.

What cannot: whether the wifi allows devices to talk to each other. No test
from a single machine can tell you that, so the report says so rather than
inventing a verdict.
"""

from __future__ import annotations

import base64
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from .pairing import local_network_address

RULE_NAME = "VU EA Conversational AI"

OK = "ok"
PROBLEM = "problem"
UNKNOWN = "unknown"


@dataclass
class Check:
    """One thing that was looked at, and what it means."""

    name: str
    status: str
    detail: str
    fix: str = ""


@dataclass
class Diagnosis:
    checks: list[Check] = field(default_factory=list)
    conclusion: str = ""
    fixable_here: bool = False
    fix_command: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "checks": [vars(check) for check in self.checks],
            "conclusion": self.conclusion,
            "fixable_here": self.fixable_here,
            "fix_command": self.fix_command,
        }


def _run(command: list[str], timeout: int = 6) -> str:
    """Run a read-only system command; return its output, or "" on any failure."""
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or "") + (completed.stderr or "")


# ------------------------------------------------------------------ checks --
def check_listening(address: str | None, port: int) -> Check:
    """Can this machine reach its own network address on that port?

    Traffic to your own address does not pass the firewall, so a failure here
    means the server is not listening there at all — a different problem from
    "listening but blocked".
    """
    if not address:
        return Check(
            "Netwerkadres",
            UNKNOWN,
            "Kon geen netwerkadres van deze computer bepalen.",
            "Controleer of deze computer met wifi of ethernet verbonden is.",
        )
    try:
        with socket.create_connection((address, port), timeout=2):
            pass
    except OSError as error:
        return Check(
            "Luistert op het netwerk",
            PROBLEM,
            f"Kan {address}:{port} niet bereiken vanaf deze computer zelf ({error.__class__.__name__}).",
            "Start de app zonder --local-only: python main.py",
        )
    return Check(
        "Luistert op het netwerk",
        OK,
        f"De app luistert op {address}:{port} en is vanaf deze computer bereikbaar.",
    )


# Eén PowerShell-aanroep die alles ophaalt als key=value. Bewust geen netsh:
# die uitvoer is vertaald (op een Nederlandse Windows staat er "Status ... AAN"),
# terwijl deze cmdlets overal True/False teruggeven.
_PROBE = """
$ErrorActionPreference = 'SilentlyContinue'
$profileInfo = Get-NetConnectionProfile | Select-Object -First 1
$category = if ($profileInfo) { [string]$profileInfo.NetworkCategory } else { '' }
$fwName = switch ($category) { 'DomainAuthenticated' { 'Domain' } 'Public' { 'Public' } default { 'Private' } }
$fw = Get-NetFirewallProfile -Profile $fwName
$rule = Get-NetFirewallRule -DisplayName '%s'
Write-Output ("CATEGORY=" + $category)
Write-Output ("PROFILE=" + $fwName)
Write-Output ("FIREWALL=" + [string]$fw.Enabled)
Write-Output ("RULE=" + [string][bool]$rule)
"""


def _probe_windows() -> dict[str, str]:
    """Ask Windows for the network category, firewall state and our rule."""
    output = _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PROBE % RULE_NAME],
        timeout=25,
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator:
            values[key.strip().upper()] = value.strip()
    return values


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "enabled"}


def check_windows_firewall(port: int) -> list[Check]:
    """Report the network category, firewall state and inbound rule."""
    if not sys.platform.startswith("win"):
        return []

    values = _probe_windows()
    if not values:
        return [
            Check(
                "Windows Firewall",
                UNKNOWN,
                "Kon de firewallstatus niet uitlezen (PowerShell gaf geen antwoord).",
                "Controleer handmatig: Windows-beveiliging > Firewall > Een app toestaan.",
            )
        ]

    checks: list[Check] = []
    category = values.get("CATEGORY", "")
    if category:
        # Een regel voor 'Privé' doet niets als Windows dit wifi als 'Openbaar'
        # ziet - een klassieke reden dat de fix "niet werkt".
        checks.append(
            Check(
                "Netwerkprofiel",
                OK,
                f"Windows ziet dit netwerk als '{category}'. De firewallregel moet dus voor "
                f"'{values.get('PROFILE', 'Private')}' gelden.",
            )
        )

    firewall_on = _is_true(values.get("FIREWALL", ""))
    checks.append(
        Check(
            "Windows Firewall",
            PROBLEM if firewall_on else OK,
            "De firewall staat aan voor dit netwerkprofiel."
            if firewall_on
            else "De firewall staat uit voor dit netwerkprofiel; die blokkeert dus niets.",
        )
    )

    has_rule = _is_true(values.get("RULE", ""))
    checks.append(
        Check(
            "Firewallregel voor deze app",
            OK if has_rule else PROBLEM,
            f"Er is een inkomende regel '{RULE_NAME}'."
            if has_rule
            else f"Er is geen inkomende regel voor poort {port}. Windows gooit verkeer van andere "
                 "apparaten dan weg zonder te antwoorden - vandaar het zwarte scherm en pas veel "
                 "later een time-out.",
            "" if has_rule else "Voeg de regel toe (vraagt eenmalig om beheerdersrechten).",
        )
    )
    return checks


def current_firewall_profile() -> str:
    """Which firewall profile applies to the network this machine is on."""
    if not sys.platform.startswith("win"):
        return "Private"
    return _probe_windows().get("PROFILE") or "Private"


def windows_firewall_command(port: int, python_path: str | None = None, profile: str | None = None) -> str:
    """Return the PowerShell command that opens this port for this app.

    Deliberately narrow: TCP only, this one port, the profile Windows actually
    applies to this network, and tied to this interpreter. Undo it with
    ``Remove-NetFirewallRule -DisplayName "VU EA Conversational AI"``.
    """
    program = python_path or sys.executable
    return (
        f'New-NetFirewallRule -DisplayName "{RULE_NAME}" -Direction Inbound -Action Allow '
        f'-Protocol TCP -LocalPort {port} -Profile {profile or current_firewall_profile()} '
        f'-Program "{program}"'
    )


def _encoded(command: str) -> str:
    """Encode a PowerShell command for -EncodedCommand.

    Passing a command with spaces and quotes through Start-Process -ArgumentList
    is a well-known way to get it silently mangled. Base64 of UTF-16LE has no
    characters that need quoting at all.
    """
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


def elevation_script(port: int, python_path: str | None = None, profile: str | None = None) -> str:
    """The outer command: ask for elevation, run the rule, pass the exit code back."""
    inner = (
        f"try {{ {windows_firewall_command(port, python_path, profile)} -ErrorAction Stop | Out-Null; exit 0 }} "
        f"catch {{ exit 1 }}"
    )
    return (
        "$p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "
        f"'-NoProfile','-EncodedCommand','{_encoded(inner)}'; exit $p.ExitCode"
    )


def apply_windows_firewall_rule(port: int, python_path: str | None = None) -> tuple[bool, str]:
    """Add the inbound rule, asking Windows for elevation.

    Returns (succeeded, message). Creating a firewall rule needs administrator
    rights, so this raises a UAC prompt; on a managed laptop where the user is
    not an administrator that prompt asks for credentials and can be refused.
    Both outcomes are reported honestly rather than assumed to have worked.
    """
    if not sys.platform.startswith("win"):
        return False, "Dit is alleen van toepassing op Windows."

    profile = current_firewall_profile()
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             elevation_script(port, python_path, profile)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Kon het venster voor beheerdersrechten niet openen: {error}"

    if completed.returncode != 0:
        return False, (
            "De regel is niet toegevoegd. Meestal is de vraag om beheerdersrechten geweigerd, of heb "
            "je op deze laptop geen beheerdersrechten. Vraag dan je IT-beheerder om poort "
            f"{port} inkomend open te zetten voor Python, profiel {profile}."
        )
    return True, (
        f"De firewallregel is toegevoegd voor profiel {profile}. Probeer je telefoon opnieuw; "
        "ververs de pagina daar."
    )


# ----------------------------------------------------------------- verdict --
def diagnose(port: int = 8501, address: str | None = None) -> Diagnosis:
    """Run every check that can be run here and draw a conclusion."""
    address = address or local_network_address()
    result = Diagnosis()
    result.checks.append(check_listening(address, port))
    result.checks.extend(check_windows_firewall(port))

    listening = result.checks[0].status
    firewall_checks = result.checks[1:]
    missing_rule = any(check.name == "Firewallregel voor deze app" and check.status == PROBLEM for check in firewall_checks)
    firewall_on = any(check.name == "Windows Firewall" and check.status == PROBLEM for check in firewall_checks)

    if listening == PROBLEM:
        result.conclusion = (
            "De app luistert niet op je netwerkadres. Start hem zonder --local-only; "
            "andere apparaten kunnen er nu sowieso niet bij."
        )
    elif firewall_on and missing_rule:
        result.conclusion = (
            "De Windows Firewall blokkeert inkomende verbindingen naar deze app. Dat verklaart "
            "precies wat je ziet: de verbinding wordt weggegooid in plaats van geweigerd, dus je "
            "telefoon wacht tot hij opgeeft. Dit is hieronder met één klik op te lossen."
        )
        result.fixable_here = True
        result.fix_command = windows_firewall_command(port)
    elif firewall_checks and not missing_rule:
        result.conclusion = (
            "De app luistert en de firewall laat hem door. Wat overblijft is het netwerk zelf: veel "
            "gast- en universiteitsnetwerken verbieden verkeer tussen apparaten (clientisolatie). "
            "Test dat door deze computer op de hotspot van je telefoon te zetten."
        )
    else:
        result.conclusion = (
            "De app luistert op je netwerkadres. Komt een ander apparaat er niet bij, dan blokkeert "
            "de firewall van deze computer het, of staat clientisolatie op het wifi-netwerk aan. "
            "Test dat laatste door deze computer op de hotspot van je telefoon te zetten."
        )
    return result
