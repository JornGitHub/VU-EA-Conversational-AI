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
    # Alleen gevuld waar het ertoe doet: het pad dat de poort openhoudt, zodat
    # de fix de juiste executable kan noemen in plaats van te gokken.
    program: str = ""


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

# De ActiveStore is wat er werkelijk geldt, inclusief wat groepsbeleid oplegt.
$rules = @(Get-NetFirewallRule -DisplayName '%s' -PolicyStore ActiveStore)
$ruleProfiles = ($rules | ForEach-Object { [string]$_.Profile }) -join '|'
$applies = $false
foreach ($r in $rules) {
    $p = [string]$r.Profile
    if ($r.Enabled -eq 'True' -and $r.Action -eq 'Allow' -and $r.Direction -eq 'Inbound' -and
        ($p -eq 'Any' -or $p -like ('*' + $fwName + '*'))) { $applies = $true }
}

# Een Block-regel wint in Windows Firewall altijd van een Allow-regel. Wie ooit
# op "Annuleren" klikte bij de firewallvraag heeft er twee, en dan haalt een
# nieuwe Allow-regel niets uit.
$blocked = @(Get-NetFirewallApplicationFilter -Program '%s' -PolicyStore ActiveStore |
             Get-NetFirewallRule |
             Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' -and $_.Enabled -eq 'True' })

Write-Output ("CATEGORY=" + $category)
Write-Output ("PROFILE=" + $fwName)
Write-Output ("FIREWALL=" + [string]$fw.Enabled)
Write-Output ("ALLOWINBOUND=" + [string]$fw.AllowInboundRules)
Write-Output ("DEFAULTIN=" + [string]$fw.DefaultInboundAction)
Write-Output ("RULE=" + [string]($rules.Count -gt 0))
Write-Output ("RULEAPPLIES=" + [string]$applies)
Write-Output ("RULEPROFILES=" + $ruleProfiles)
Write-Output ("BLOCKED=" + [string]$blocked.Count)
Write-Output ("ADMIN=" + [string](([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)))
"""


def _probe_windows() -> dict[str, str]:
    """Ask Windows for the network category, firewall state and our rule."""
    output = _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         _PROBE % (RULE_NAME, sys.executable.replace("'", "''"))],
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

    blocked = values.get("BLOCKED", "0")
    if blocked.isdigit() and int(blocked) > 0:
        checks.append(
            Check(
                "Blokkeerregel voor Python",
                PROBLEM,
                f"Er staan {blocked} actieve blokkeerregels voor deze Python. Die ontstaan als ooit op "
                "'Annuleren' is geklikt bij de firewallvraag van Windows. Een blokkeerregel wint altijd "
                "van een toestaan-regel, dus die moeten eerst weg.",
                "Verwijderen (vraagt beheerdersrechten): "
                f"Get-NetFirewallApplicationFilter -Program '{sys.executable}' | Get-NetFirewallRule | "
                "Where-Object { $_.Action -eq 'Block' } | Remove-NetFirewallRule",
            )
        )

    if values.get("ADMIN") and not _is_true(values.get("ADMIN", "")):
        checks.append(
            Check(
                "Beheerdersrechten",
                UNKNOWN,
                "Je draait zonder beheerdersrechten. Windows vraagt er straks om; op een beheerde laptop "
                "kan die vraag om inloggegevens vragen die je niet hebt.",
            )
        )

    # Groepsbeleid kan inkomende toestaan-regels domweg negeren. Dan staat de
    # regel er wel, en doet hij niets - precies het geval waarin "er is een
    # regel" een geruststelling zou zijn die nergens op slaat.
    allow_inbound = values.get("ALLOWINBOUND", "")
    if allow_inbound and allow_inbound.strip().lower() == "false":
        checks.append(
            Check(
                "Inkomende regels toegestaan",
                PROBLEM,
                f"Het beleid op deze laptop negeert álle inkomende toestaan-regels op profiel "
                f"'{values.get('PROFILE', '')}'. Een firewallregel toevoegen verandert dus niets.",
                "Dit is beleid van je organisatie en niet vanuit de app te wijzigen.",
            )
        )

    has_rule = _is_true(values.get("RULE", ""))
    applies = _is_true(values.get("RULEAPPLIES", ""))
    profiles = values.get("RULEPROFILES", "").replace("|", ", ")
    current = values.get("PROFILE", "")

    if has_rule and not applies:
        checks.append(
            Check(
                "Firewallregel voor deze app",
                PROBLEM,
                f"Er is een regel '{RULE_NAME}', maar die geldt voor "
                f"{profiles or 'een ander profiel'} en dit netwerk is '{current}'. Daardoor doet hij "
                "hier niets - dat is precies waarom het lijkt alsof de fix niet werkte.",
                f"Vervang de regel door één voor profiel '{current}'.",
            )
        )
    else:
        checks.append(
            Check(
                "Firewallregel voor deze app",
                OK if applies else PROBLEM,
                f"Er is een inkomende regel '{RULE_NAME}' die geldt voor dit netwerk ({current})."
                if applies
                else f"Er is geen inkomende regel voor poort {port}. Windows gooit verkeer van andere "
                     "apparaten dan weg zonder te antwoorden - vandaar het zwarte scherm en pas veel "
                     "later een time-out.",
                "" if applies else "Voeg de regel toe (vraagt eenmalig om beheerdersrechten).",
            )
        )
    return checks


# Een tweede, tragere ronde. Apart gehouden zodat het opsommen van alle regels
# de snelle basischecks niet kan ophouden of laten omvallen.
_DEEP_PROBE = """
$ErrorActionPreference = 'SilentlyContinue'
$profileInfo = Get-NetConnectionProfile | Select-Object -First 1
$category = if ($profileInfo) { [string]$profileInfo.NetworkCategory } else { '' }
$fwName = switch ($category) { 'DomainAuthenticated' { 'Domain' } 'Public' { 'Public' } default { 'Private' } }

# Andere beveiligingssoftware met een eigen firewall. Op een beheerde laptop is
# dit de meest voorkomende reden dat Windows Firewall in orde lijkt en er tóch
# niets doorkomt.
$products = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct |
              ForEach-Object { [string]$_.displayName } |
              Where-Object { $_ -and $_ -notmatch 'Windows (Defender )?Firewall' })
Write-Output ("FIREWALLPRODUCTS=" + ($products -join '|'))

# Blokkeerregels die niet aan ons programma hangen: een beleidsregel die alle
# inkomend verkeer op dit profiel dichtzet, wint ook van onze toestaan-regel.
$broad = @(Get-NetFirewallRule -PolicyStore ActiveStore -Direction Inbound -Action Block -Enabled True |
           Where-Object { $_.Profile -eq 'Any' -or $_.Profile -like ('*' + $fwName + '*') } |
           Where-Object {
               $port = $_ | Get-NetFirewallPortFilter
               $app = $_ | Get-NetFirewallApplicationFilter
               (-not $port -or $port.LocalPort -eq 'Any' -or $port.LocalPort -contains '%s') -and
               (-not $app -or $app.Program -eq 'Any')
           })
Write-Output ("BROADBLOCKS=" + [string]$broad.Count)
Write-Output ("BROADNAMES=" + (($broad | Select-Object -First 4 | ForEach-Object { [string]$_.DisplayName }) -join '|'))
"""


def _deep_probe(port: int) -> dict[str, str]:
    """Second round: other security products, and broad inbound block rules."""
    output = _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _DEEP_PROBE % port],
        timeout=60,
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator:
            values[key.strip().upper()] = value.strip()
    return values


# Welk proces houdt de poort werkelijk open, en op welk adres? Een firewallregel
# geldt voor één programma; hoort de poort bij een ándere python.exe dan die in
# de regel staat, dan doet de regel niets voor dit proces.
_LISTENER_PROBE = """
$ErrorActionPreference = 'SilentlyContinue'
$conns = @(Get-NetTCPConnection -LocalPort %s -State Listen)
$addresses = ($conns | ForEach-Object { [string]$_.LocalAddress } | Sort-Object -Unique) -join '|'
$paths = @()
foreach ($id in ($conns | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)) {
    $proc = Get-Process -Id $id
    if ($proc -and $proc.Path) { $paths += [string]$proc.Path }
}
# Wat de regel wérkelijk toestaat, uit Windows zelf. Aannemen dat dat
# sys.executable is, is precies de fout die deze check moet vinden.
$rules = @(Get-NetFirewallRule -DisplayName '%s' -PolicyStore ActiveStore |
           Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' -and $_.Enabled -eq 'True' })
$rulePrograms = @($rules | Get-NetFirewallApplicationFilter | ForEach-Object { [string]$_.Program })
Write-Output ("LISTENADDRESSES=" + $addresses)
Write-Output ("LISTENPATHS=" + (($paths | Sort-Object -Unique) -join '|'))
Write-Output ("RULEPROGRAMS=" + (($rulePrograms | Sort-Object -Unique) -join '|'))
"""


def listening_program(port: int) -> str | None:
    """Return the executable Windows sees holding this port, if it can tell.

    This is the path a firewall rule has to name. It is not always
    ``sys.executable``: a virtual environment's python.exe can run under the
    base interpreter's image, and the firewall matches on the image.
    """
    if not sys.platform.startswith("win"):
        return None
    for line in _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _LISTENER_PROBE % (port, RULE_NAME)],
        timeout=30,
    ).splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip().upper() == "LISTENPATHS":
            paths = [item for item in value.split("|") if item.strip()]
            return paths[0] if paths else None
    return None


def check_listener_matches_rule(port: int) -> list[Check]:
    """Does the firewall rule name the executable that owns the port?

    A rule is bound to one program. Start the app with one interpreter and
    create the rule from another - a virtual environment next to the system
    Python, say - and the rule is perfectly valid and completely irrelevant.
    """
    if not sys.platform.startswith("win"):
        return []

    values: dict[str, str] = {}
    for line in _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _LISTENER_PROBE % (port, RULE_NAME)],
        timeout=30,
    ).splitlines():
        key, separator, value = line.strip().partition("=")
        if separator:
            values[key.strip().upper()] = value.strip()
    if not values:
        return []

    checks: list[Check] = []
    addresses = [item for item in values.get("LISTENADDRESSES", "").split("|") if item.strip()]
    if addresses and not any(item in {"0.0.0.0", "::"} for item in addresses):
        checks.append(
            Check(
                "Luisteradres",
                PROBLEM,
                f"Poort {port} staat alleen open op {', '.join(addresses)}, niet op alle interfaces. "
                "Andere apparaten kunnen er daardoor niet bij.",
                "Start de app zonder --local-only: python main.py",
            )
        )

    paths = [item for item in values.get("LISTENPATHS", "").split("|") if item.strip()]
    allowed = [item for item in values.get("RULEPROGRAMS", "").split("|") if item.strip()]
    if not paths or not allowed:
        # Zonder een van beide valt er niets te vergelijken; de losse checks
        # voor "luistert de app" en "is er een regel" dekken die gevallen al.
        return checks

    # "Any" betekent: de regel is niet aan een programma gebonden.
    covered = {item.lower() for item in allowed}
    matches = "any" in covered or any(item.lower() in covered for item in paths)
    if matches:
        checks.append(
            Check(
                "Programma achter de poort",
                OK,
                f"Poort {port} wordt opengehouden door {paths[0]}, en de firewallregel geldt voor dat "
                "programma.",
            )
        )
    else:
        checks.append(
            Check(
                "Programma achter de poort",
                PROBLEM,
                f"Poort {port} wordt opengehouden door {', '.join(paths)}, terwijl de firewallregel geldt "
                f"voor {', '.join(allowed)}. Een regel hoort bij één programma, dus die doet hier niets.",
                "Maak de regel opnieuw aan voor het programma dat de poort vasthoudt.",
                paths[0],
            )
        )
    return checks


def check_other_blockers(port: int) -> list[Check]:
    """Look for what blocks traffic while Windows Firewall looks fine."""
    if not sys.platform.startswith("win"):
        return []

    values = _deep_probe(port)
    if not values:
        return []

    checks: list[Check] = []
    products = [name for name in values.get("FIREWALLPRODUCTS", "").split("|") if name.strip()]
    if products:
        checks.append(
            Check(
                "Andere beveiligingssoftware",
                PROBLEM,
                "Naast Windows Firewall draait hier ook: " + ", ".join(products) + ". "
                "Zulke pakketten hebben een eigen firewall die inkomend verkeer los van Windows "
                "blokkeert - dat verklaart waarom Windows Firewall in orde is en er tóch niets doorkomt.",
                "Sta poort " + str(port) + " inkomend toe in dat pakket, of vraag je IT-beheerder dat te doen.",
            )
        )

    count = values.get("BROADBLOCKS", "0")
    if count.isdigit() and int(count) > 0:
        names = [name for name in values.get("BROADNAMES", "").split("|") if name.strip()]
        checks.append(
            Check(
                "Brede blokkeerregels",
                PROBLEM,
                f"Er staan {count} inkomende blokkeerregels die niet aan een programma hangen en dit "
                f"profiel raken" + (f" ({', '.join(names)})" if names else "") + ". Zulke regels winnen "
                "van onze toestaan-regel.",
                "Meestal opgelegd door je organisatie; niet vanuit de app te wijzigen.",
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
    applies to this network, and tied to one program. That program is the one
    holding the port, which is not always ``sys.executable`` - naming the wrong
    one produces a rule that is valid and does nothing. Undo it with
    ``Remove-NetFirewallRule -DisplayName "VU EA Conversational AI"``.
    """
    program = python_path or listening_program(port) or sys.executable
    # Eerst weg, dan opnieuw: anders staat een oude regel voor het verkeerde
    # profiel er nog naast en verandert er niets.
    return (
        f'Remove-NetFirewallRule -DisplayName "{RULE_NAME}" -ErrorAction SilentlyContinue; '
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


def elevation_script(port: int, python_path: str | None = None, profile: str | None = None,
                     report_path: str = "") -> str:
    """The outer command: ask for elevation, run the rule, keep the error.

    The elevated window closes the moment it is done, so a failure used to
    flash past unread — which is exactly the message needed to know whether
    this is group policy, a missing right, or something else. The inner script
    therefore writes its outcome to a file the caller can read afterwards.
    """
    report = report_path or "$env:TEMP\\vu-ea-firewall.txt"
    inner = (
        f"$out = '{report}'; "
        f"try {{ {windows_firewall_command(port, python_path, profile)} -ErrorAction Stop | Out-Null; "
        f"Set-Content -Path $out -Value 'OK' -Encoding ASCII; exit 0 }} "
        f"catch {{ Set-Content -Path $out -Value $_.Exception.Message -Encoding UTF8; exit 1 }}"
    )
    return (
        f"$out = '{report}'; Remove-Item $out -ErrorAction SilentlyContinue; "
        "try { $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "
        f"'-NoProfile','-EncodedCommand','{_encoded(inner)}'; exit $p.ExitCode }} "
        "catch { exit 2 }"
    )


def _read_report(report_path: str) -> str:
    """Read (and remove) whatever the elevated script left behind."""
    from pathlib import Path as _Path

    try:
        file = _Path(report_path)
        # PowerShell 5.1 zet een BOM voor de inhoud; zonder strippen leest een
        # geslaagde run als een mislukte.
        message = file.read_text(encoding="utf-8-sig", errors="replace").strip().lstrip("\ufeff")
        file.unlink(missing_ok=True)
    except OSError:
        return ""
    return message


def is_administrator() -> bool:
    """True when this process can create firewall rules without elevating."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - never let a probe break the panel
        return False


def it_request_text(port: int, python_path: str | None = None) -> str:
    """A message to send to whoever does have the rights, ready to paste."""
    return (
        "Verzoek: sta binnenkomend TCP-verkeer toe op poort "
        f"{port} voor {python_path or sys.executable}, alleen op het huidige netwerkprofiel.\n"
        "Reden: een lokale Streamlit-app (VU EA Conversational AI) moet vanaf een telefoon op hetzelfde "
        "netwerk te openen zijn. De app draait volledig lokaal en stuurt geen data naar buiten.\n"
        "Regel:\n  " + windows_firewall_command(port, python_path)
    )


def apply_windows_firewall_rule(port: int, python_path: str | None = None) -> tuple[bool, str]:
    """Add the inbound rule, asking Windows for elevation.

    Returns (succeeded, message). Creating a firewall rule needs administrator
    rights, so this raises a UAC prompt; on a managed laptop that prompt can
    ask for credentials the user does not have, and group policy can refuse the
    rule even to an administrator. Both are reported with the message Windows
    itself gave, instead of a generic failure.
    """
    if not sys.platform.startswith("win"):
        return False, "Dit is alleen van toepassing op Windows."

    import os
    import tempfile

    profile = current_firewall_profile()
    report_path = os.path.join(tempfile.gettempdir(), "vu-ea-firewall.txt")
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             elevation_script(port, python_path, profile, report_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Kon het venster voor beheerdersrechten niet openen: {error}"

    # De BOM wordt bij het lezen al gestript, maar de beslissing hangt hiervan af
    # en mag niet omvallen op een byte die je niet ziet staan.
    reported = _read_report(report_path).lstrip("\ufeff").strip()
    if completed.returncode == 0 and reported.upper().startswith("OK"):
        return True, (
            f"De firewallregel is toegevoegd voor profiel {profile}. Probeer je telefoon opnieuw en "
            "ververs de pagina daar."
        )

    if completed.returncode == 2 or not reported:
        # De verhoogde PowerShell is nooit gestart: UAC geweigerd of geblokkeerd.
        return False, (
            "Windows heeft het venster met beheerdersrechten niet geopend, of de vraag is geweigerd. "
            "Heb je op deze laptop geen beheerdersrechten, dan kan dit niet vanuit de app - zie het "
            "verzoek voor je IT-beheerder hieronder."
        )

    return False, (
        f"Windows weigerde de regel:\n\n{reported}\n\n"
        "Staat hier iets over 'group policy' of 'toegang geweigerd', dan verbiedt het beleid van je "
        "organisatie het aanmaken van firewallregels. Dat is niet vanuit de app op te lossen; gebruik "
        "het verzoek voor je IT-beheerder hieronder, of de hotspot van je telefoon als tijdelijke route."
    )


# ----------------------------------------------------------------- verdict --
def diagnose(port: int = 8501, address: str | None = None) -> Diagnosis:
    """Run every check that can be run here and draw a conclusion."""
    address = address or local_network_address()
    result = Diagnosis()
    result.checks.append(check_listening(address, port))
    result.checks.extend(check_windows_firewall(port))
    # Alleen dieper graven als Windows Firewall zelf niets verklaart; anders is
    # de oorzaak al gevonden en kost dit alleen tijd.
    windows_explains = any(check.status == PROBLEM and check.name != "Windows Firewall" for check in result.checks[1:])
    if not windows_explains:
        result.checks.extend(check_listener_matches_rule(port))
        windows_explains = any(check.status == PROBLEM and check.name != "Windows Firewall" for check in result.checks[1:])
    if not windows_explains:
        result.checks.extend(check_other_blockers(port))

    listening = result.checks[0].status
    firewall_checks = result.checks[1:]
    missing_rule = any(check.name == "Firewallregel voor deze app" and check.status == PROBLEM for check in firewall_checks)
    firewall_on = any(check.name == "Windows Firewall" and check.status == PROBLEM for check in firewall_checks)
    has_block_rule = any(check.name == "Blokkeerregel voor Python" for check in firewall_checks)
    inbound_ignored = any(check.name == "Inkomende regels toegestaan" for check in firewall_checks)
    other_product = next((check for check in firewall_checks if check.name == "Andere beveiligingssoftware"), None)
    wrong_program_check = next(
        (check for check in firewall_checks if check.name == "Programma achter de poort" and check.status == PROBLEM),
        None,
    )
    wrong_program = wrong_program_check is not None
    narrow_listen = any(check.name == "Luisteradres" and check.status == PROBLEM for check in firewall_checks)
    broad_blocks = any(check.name == "Brede blokkeerregels" for check in firewall_checks)
    wrong_profile = any(
        check.name == "Firewallregel voor deze app" and check.status == PROBLEM and "maar die geldt voor" in check.detail
        for check in firewall_checks
    )

    if listening == PROBLEM:
        result.conclusion = (
            "De app luistert niet op je netwerkadres. Start hem zonder --local-only; "
            "andere apparaten kunnen er nu sowieso niet bij."
        )
    elif inbound_ignored:
        result.conclusion = (
            "Het beleid op deze laptop negeert inkomende toestaan-regels op dit netwerkprofiel. Een "
            "firewallregel toevoegen verandert dus niets, hoe vaak je het ook probeert. Twee routes "
            "blijven over: zet deze laptop op de hotspot van je telefoon, of gebruik voor opzoekwerk de "
            "zoekpagina die geen verbinding met deze laptop nodig heeft "
            "(https://jorngithub.github.io/VU-EA-Conversational-AI/zoek.html)."
        )
    elif has_block_rule:
        result.conclusion = (
            "Er staat een blokkeerregel voor deze Python in de firewall. Die wint van elke toestaan-regel, "
            "dus die moet eerst weg - anders verandert het toevoegen van een regel niets. Het commando "
            "daarvoor staat hierboven; het vraagt om beheerdersrechten."
        )
    elif wrong_profile:
        result.conclusion = (
            "De firewallregel bestaat wel, maar geldt voor een ander netwerkprofiel dan waar je nu op "
            "zit. Daardoor doet hij niets - dat is waarom het leek alsof de fix niet werkte. Hieronder "
            "kun je hem vervangen door één voor het juiste profiel."
        )
        result.fixable_here = True
        result.fix_command = windows_firewall_command(port)
    elif firewall_on and missing_rule:
        result.conclusion = (
            "De Windows Firewall blokkeert inkomende verbindingen naar deze app. Dat verklaart "
            "precies wat je ziet: de verbinding wordt weggegooid in plaats van geweigerd, dus je "
            "telefoon wacht tot hij opgeeft. Dit is hieronder met één klik op te lossen."
        )
        result.fixable_here = True
        result.fix_command = windows_firewall_command(port)
    elif narrow_listen:
        result.conclusion = (
            "De poort staat niet op alle netwerkinterfaces open, dus andere apparaten kunnen er niet bij. "
            "Start de app opnieuw met `python main.py` (zonder --local-only)."
        )
    elif wrong_program:
        result.conclusion = (
            "De firewallregel geldt voor een andere python.exe dan degene die de poort openhoudt. Een "
            "regel hoort bij één programma, dus deze doet niets voor de draaiende app. De knop hieronder "
            "maakt de regel opnieuw aan, nu voor het programma dat de poort werkelijk vasthoudt."
        )
        result.fixable_here = True
        result.fix_command = windows_firewall_command(port, wrong_program_check.program or None)
    elif other_product is not None:
        result.conclusion = (
            "Windows Firewall laat de app door, maar er draait andere beveiligingssoftware met een eigen "
            "firewall. Dat is op een beheerde laptop de meest voorkomende reden dat alles in Windows in "
            "orde lijkt en er tóch niets doorkomt. Zie de bevinding hierboven; de app kan daar niets aan "
            "veranderen. Tot dat geregeld is: gebruik de hotspot van je telefoon, of de zoekpagina die "
            "geen verbinding met deze laptop nodig heeft "
            "(https://jorngithub.github.io/VU-EA-Conversational-AI/zoek.html)."
        )
    elif broad_blocks:
        result.conclusion = (
            "Er staan brede inkomende blokkeerregels op dit netwerkprofiel die niet aan een programma "
            "hangen. Die winnen van onze toestaan-regel, dus de app blijft onbereikbaar zolang ze er "
            "staan. Dat is beleid van je organisatie en niet vanuit de app te wijzigen."
        )
    elif firewall_checks and not missing_rule:
        result.conclusion = (
            "De app luistert en de firewall laat hem door voor dit netwerkprofiel, en er is geen andere "
            "beveiligingssoftware gevonden die inkomend verkeer blokkeert. Wat overblijft is het "
            "netwerk zelf: veel gast- en universiteitsnetwerken verbieden verkeer tussen apparaten "
            "(clientisolatie). Test dat door deze computer op de hotspot van je telefoon te zetten - "
            "werkt het daar wel, dan was dit de oorzaak. Gaat het je alleen om opzoeken, dan werkt de "
            "zoekpagina op elke telefoon zonder verbinding met deze laptop: "
            "https://jorngithub.github.io/VU-EA-Conversational-AI/zoek.html"
        )
    else:
        result.conclusion = (
            "De app luistert op je netwerkadres. Komt een ander apparaat er niet bij, dan blokkeert "
            "de firewall van deze computer het, of staat clientisolatie op het wifi-netwerk aan. "
            "Test dat laatste door deze computer op de hotspot van je telefoon te zetten."
        )
    return result
