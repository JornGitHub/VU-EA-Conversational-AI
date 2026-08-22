"""Everything needed to open the app on a phone: the address, and a QR code.

The app runs on one machine; a phone on the same network only needs the right
URL. Typing an IP address on a phone is exactly the kind of small friction that
stops people using a tool, so this also renders that URL as a QR code.

Nothing here reaches outside the machine: the address is read from the local
interfaces and the QR code is drawn locally.
"""

from __future__ import annotations

import socket
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


def pairing_status(server_address: str | None, port: int = 8501) -> dict[str, Any]:
    """Describe how (or whether) a phone can reach this app right now."""
    url = pairing_url(port)
    reachable = is_reachable_from_network(server_address)
    return {
        "reachable": bool(reachable and url),
        "url": url if reachable else None,
        "server_address": server_address,
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
