"""Guard the phone-pairing panel: a wrong address is worse than none."""

from __future__ import annotations

import unittest
from unittest import mock

from src import pairing


class ReachabilityTests(unittest.TestCase):
    def test_localhost_is_not_reachable_from_a_phone(self) -> None:
        """Streamlit's default binds to loopback; no URL would work then."""
        for address in ("localhost", "127.0.0.1", "::1", None):
            self.assertFalse(pairing.is_reachable_from_network(address), address)

    def test_wildcard_binds_are_reachable(self) -> None:
        for address in ("0.0.0.0", "::"):
            self.assertTrue(pairing.is_reachable_from_network(address), address)

    def test_an_unset_address_counts_as_not_reachable(self) -> None:
        """Guessing wrong here shows a URL that silently fails on the phone."""
        self.assertFalse(pairing.is_reachable_from_network(""))

    def test_status_explains_how_to_restart_instead_of_showing_a_dead_url(self) -> None:
        status = pairing.pairing_status("localhost")
        self.assertFalse(status["reachable"])
        self.assertIsNone(status["url"])
        self.assertIn("--network", status["hint"])

    def test_status_returns_a_url_when_the_app_listens_broadly(self) -> None:
        with mock.patch.object(pairing, "local_network_address", return_value="192.168.1.24"):
            status = pairing.pairing_status("0.0.0.0", port=8502)
        self.assertTrue(status["reachable"])
        self.assertEqual("http://192.168.1.24:8502", status["url"])
        self.assertEqual("", status["hint"])

    def test_loopback_addresses_are_never_offered_as_the_pairing_url(self) -> None:
        with mock.patch.object(pairing.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 0)
            self.assertIsNone(pairing.local_network_address())

    def test_an_unreachable_network_is_reported_rather_than_crashing(self) -> None:
        with mock.patch.object(pairing.socket, "socket", side_effect=OSError("geen netwerk")):
            self.assertIsNone(pairing.local_network_address())


class QrTests(unittest.TestCase):
    def test_qr_encodes_exactly_the_url(self) -> None:
        """A QR that points somewhere else is a silent trap."""
        try:
            import segno  # noqa: F401
        except ImportError:
            self.skipTest("segno niet geïnstalleerd")
        url = "http://192.168.1.24:8501"
        svg = pairing.qr_svg(url)
        self.assertIsNotNone(svg)
        self.assertIn("<svg", svg)
        import segno

        expected_side = segno.make(url, error="m").symbol_size(scale=4, border=2)[0]
        self.assertIn(f'width="{expected_side}"', svg)

    def test_a_missing_library_costs_a_qr_and_nothing_else(self) -> None:
        """The panel must still render; the URL alone is enough to type."""
        import builtins

        real_import = builtins.__import__

        def refuse_segno(name, *args, **kwargs):
            if name == "segno":
                raise ImportError("segno ontbreekt")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", refuse_segno):
            self.assertIsNone(pairing.qr_svg("http://192.168.1.24:8501"))
        self.assertIn("segno", pairing.QR_UNAVAILABLE_HINT)


class EntryPointTests(unittest.TestCase):
    def test_network_flag_widens_the_bind_address(self) -> None:
        import main

        with mock.patch.object(main, "run_command", return_value=0) as run:
            main.run_streamlit(share_on_network=True)
        command = run.call_args[0][0]
        self.assertIn("--server.address", command)
        self.assertIn("0.0.0.0", command)

    def test_default_start_stays_on_this_machine(self) -> None:
        import main

        with mock.patch.object(main, "run_command", return_value=0) as run:
            main.run_streamlit()
        self.assertNotIn("--server.address", run.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
