"""Everything needed to open the app on a phone: the address, and a QR code.

The app runs on one machine; a phone on the same network only needs the right
URL. Typing an IP address on a phone is exactly the kind of small friction that
stops people using a tool, so this also renders that URL as a QR code.

Nothing here reaches outside the machine: the address is read from the local
interfaces and the QR code is drawn locally.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
from typing import Any

QR_UNAVAILABLE_HINT = (
    "Installeer `segno` voor een scanbare QR-code: pip install segno "
    "(of draai `python main.py`, dat installeert hem mee)."
)


def local_network_address() -> str | None:
    """Return this machine's address on the local network, or None.

    Opening a UDP socket towards a routable address makes the OS pick the
    interface it would actually use; no packet is sent.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return address if address and not address.startswith("127.") else None


def is_local_network_address(address: str | None) -> bool:
    """True for an address that only exists inside your own network.

    Home wifi hands out 192.168.x.x or 10.x.x.x: addresses a phone on that same
    wifi can reach. A university network like eduroam usually hands out a public
    address instead (130.37.x.x at the VU). That difference matters, because a
    network that gives its clients public addresses is nearly always a network
    that keeps those clients apart - and then nothing on this laptop helps.
    """
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version != 4 or parsed.is_loopback or parsed.is_link_local:
        return False
    # Subnetmaskers als 255.255.255.0 vallen in het gereserveerde bereik en
    # tellen bij Python als "private"; die komen uit ipconfig-uitvoer mee.
    if parsed.is_reserved or parsed.is_multicast or parsed.is_unspecified:
        return False
    return parsed.is_private


def _is_usable(address: str) -> bool:
    """Keep addresses a phone on the same network could reach."""
    return is_local_network_address(address)


def _addresses_from_hostname() -> list[str]:
    """Ask the OS for this machine's own addresses.

    On Windows this usually returns every adapter; on Linux it often returns
    only loopback, which is why it is one source among several.
    """
    found: list[str] = []
    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
        found.extend(addresses)
    except (OSError, UnicodeError):
        pass
    try:
        found.extend(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except (OSError, UnicodeError):
        pass
    return found


def _addresses_from_system() -> list[str]:
    """Read the interface list from the OS tooling, as a last source.

    A laptop with a VPN, Docker or a second adapter has several addresses and
    only one of them is the wifi the phone is on; guessing one and hiding the
    rest is what leaves someone staring at a blank page.
    """
    if sys.platform.startswith("win"):
        command = ["ipconfig"]
    elif sys.platform == "darwin":
        command = ["ifconfig"]
    else:
        command = ["ip", "-4", "-o", "addr", "show"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return []
    return re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", completed.stdout or "")


def _belongs_to_this_machine(address: str) -> bool:
    """True when a socket can bind to this address, so it is really ours.

    Needed because reading ``ipconfig``/``ip addr`` output with a plain address
    pattern also picks up subnet masks, gateways and DNS servers. Offering one
    of those as "try this instead" would send someone chasing an address that
    was never going to answer. Binding is the OS's own answer to the question.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((address, 0))
    except OSError:
        return False
    return True


def local_network_addresses() -> list[str]:
    """Return every address a phone might use, best guess first.

    The routed address (the interface the OS would use to reach the internet)
    comes first because it is right on a plain laptop-on-wifi; the rest are
    there for the machine where it is not.
    """
    ordered: list[str] = []
    primary = local_network_address()
    if primary:
        ordered.append(primary)
    for address in _addresses_from_hostname() + _addresses_from_system():
        if address in ordered or not _is_usable(address):
            continue
        if _belongs_to_this_machine(address):
            ordered.append(address)
    return ordered


def is_reachable_from_network(server_address: str | None) -> bool:
    """True when Streamlit listens on more than the loopback interface.

    Streamlit's default binds to localhost, and then no phone can reach it no
    matter what the URL says — better to say so than to show a dead address.
    """
    # Leeg of niet gezet: behandelen als loopback. Fout raden kost iemand een
    # adres dat niet werkt; te voorzichtig raden kost een herstart die sowieso
    # in het paneel staat.
    if not server_address:
        return False
    return server_address in {"0.0.0.0", "::"}


def pairing_url(port: int = 8501) -> str | None:
    address = local_network_address()
    return f"http://{address}:{port}" if address else None


def pairing_urls(port: int = 8501) -> list[str]:
    """Every address worth trying, best guess first."""
    return [f"http://{address}:{port}" for address in local_network_addresses()]


def qr_svg(url: str, scale: int = 4) -> str | None:
    """Return the URL as an inline SVG QR code, or None without the library.

    Optional dependency: a missing QR code costs a phone user one typed
    address, so it must never be the reason the sidebar fails to render.
    """
    try:
        import segno
    except ImportError:
        return None

    import io

    # segno schrijft SVG als bytes, ook naar een tekstbuffer; vandaar BytesIO.
    buffer = io.BytesIO()
    segno.make(url, error="m").save(
        buffer, kind="svg", scale=scale, border=2, xmldecl=False, svgclass=None, lineclass=None
    )
    return buffer.getvalue().decode("utf-8")


def reachable_urls_wanted(server_address: str | None) -> bool:
    """Only enumerate interfaces when the app actually listens broadly."""
    return is_reachable_from_network(server_address)


PUBLIC_ADDRESS_WARNING = (
    "Dit is geen adres binnen je eigen wifi maar een publiek adres dat het netwerk zelf heeft "
    "uitgedeeld — typisch voor een universiteits- of kantoornetwerk zoals eduroam. Zulke netwerken "
    "houden apparaten vrijwel altijd uit elkaar, en dan komt je telefoon hier niet bij, hoe goed de "
    "firewall ook staat. De route die dan wél werkt: zet de hotspot van je telefoon aan, verbind deze "
    "laptop daarmee en herstart de app — de telefoon is dan zelf het netwerk."
)


def pairing_status(server_address: str | None, port: int = 8501) -> dict[str, Any]:
    """Describe how (or whether) a phone can reach this app right now."""
    url = pairing_url(port)
    urls = pairing_urls(port) if reachable_urls_wanted(server_address) else []
    reachable = is_reachable_from_network(server_address)
    address = local_network_address()
    # Het primaire adres komt van de routeringstest, niet uit de gefilterde
    # lijst: op eduroam is dat een publiek adres, en juist dan moet het paneel
    # zeggen wat er aan de hand is in plaats van een QR-code te tonen die het
    # nooit gaat doen.
    public_address = bool(reachable and address and not is_local_network_address(address))
    return {
        "reachable": bool(reachable and url),
        "url": url if reachable else None,
        "alternatives": [other for other in urls if other != url] if reachable else [],
        "port": port,
        "server_address": server_address,
        "public_address": public_address,
        "warning": PUBLIC_ADDRESS_WARNING if public_address else "",
        "hint": (
            ""
            if reachable and url
            else (
                "De app luistert alleen op deze computer. Stop hem (Ctrl+C) en start opnieuw met "
                "`python main.py --network`, dan is hij ook op je telefoon te openen."
                if not reachable
                else "Kon het netwerkadres van deze computer niet bepalen."
            )
        ),
    }
