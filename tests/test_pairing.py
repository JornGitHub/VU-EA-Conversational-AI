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


class AddressEnumerationTests(unittest.TestCase):
    """One guessed address is not enough on a laptop with a VPN or Docker.

    A phone that gets the wrong address shows a blank page and then times out,
    which looks exactly like the app being broken.
    """

    def test_only_private_reachable_addresses_are_offered(self) -> None:
        for address in ("192.168.1.24", "10.0.0.5", "172.16.3.9"):
            self.assertTrue(pairing._is_usable(address), address)
        for address in (
            "127.0.0.1", "169.254.10.2", "8.8.8.8", "::1", "niet-een-adres", "",
            "255.255.255.0", "255.255.0.0", "224.0.0.1", "0.0.0.0",
        ):
            self.assertFalse(pairing._is_usable(address), address)

    def test_the_routed_address_comes_first(self) -> None:
        """It is right on a plain laptop-on-wifi, so it stays the headline."""
        with mock.patch.object(pairing, "local_network_address", return_value="192.168.1.24"), \
             mock.patch.object(pairing, "_addresses_from_hostname", return_value=["172.17.0.1"]), \
             mock.patch.object(pairing, "_addresses_from_system", return_value=["10.8.0.2", "192.168.1.24"]), \
             mock.patch.object(pairing, "_belongs_to_this_machine", return_value=True):
            self.assertEqual(["192.168.1.24", "172.17.0.1", "10.8.0.2"], pairing.local_network_addresses())

    def test_duplicates_and_junk_are_dropped(self) -> None:
        with mock.patch.object(pairing, "local_network_address", return_value="192.168.1.24"), \
             mock.patch.object(pairing, "_addresses_from_hostname", return_value=["192.168.1.24", "127.0.0.1"]), \
             mock.patch.object(pairing, "_addresses_from_system", return_value=["255.255.255.0", "8.8.8.8"]), \
             mock.patch.object(pairing, "_belongs_to_this_machine", return_value=True):
            self.assertEqual(["192.168.1.24"], pairing.local_network_addresses())

    def test_addresses_that_are_not_ours_are_dropped(self) -> None:
        """Reading ipconfig also yields subnet masks, gateways and DNS servers.

        Those are private-looking and would be offered as "try this instead",
        sending someone after an address that was never going to answer.
        """
        self.assertFalse(pairing._belongs_to_this_machine("255.255.255.0"))
        self.assertFalse(pairing._belongs_to_this_machine("192.168.255.254"))
        self.assertTrue(pairing._belongs_to_this_machine("127.0.0.1"))

        with mock.patch.object(pairing, "local_network_address", return_value=None), \
             mock.patch.object(pairing, "_addresses_from_hostname", return_value=[]), \
             mock.patch.object(pairing, "_addresses_from_system", return_value=["192.168.1.1", "10.44.0.9"]):
            self.assertEqual([], pairing.local_network_addresses())

    def test_status_lists_the_alternatives_separately(self) -> None:
        with mock.patch.object(pairing, "local_network_address", return_value="192.168.1.24"), \
             mock.patch.object(pairing, "local_network_addresses", return_value=["192.168.1.24", "10.8.0.2"]):
            status = pairing.pairing_status("0.0.0.0", port=8501)
        self.assertEqual("http://192.168.1.24:8501", status["url"])
        self.assertEqual(["http://10.8.0.2:8501"], status["alternatives"])
        self.assertEqual(8501, status["port"])

    def test_nothing_is_enumerated_when_the_app_is_local_only(self) -> None:
        status = pairing.pairing_status("localhost")
        self.assertEqual([], status["alternatives"])

    def test_a_failing_system_command_costs_nothing(self) -> None:
        """ipconfig/ip may be absent or slow; that must not break the panel."""
        with mock.patch.object(pairing.subprocess, "run", side_effect=OSError("geen ipconfig")):
            self.assertEqual([], pairing._addresses_from_system())

    def test_a_broken_hostname_lookup_costs_nothing(self) -> None:
        with mock.patch.object(pairing.socket, "gethostbyname_ex", side_effect=OSError), \
             mock.patch.object(pairing.socket, "getaddrinfo", side_effect=OSError):
            self.assertEqual([], pairing._addresses_from_hostname())


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
    def test_the_default_start_is_reachable_from_a_phone(self) -> None:
        """No button can widen the bind address after startup, so this is it."""
        import main

        with mock.patch.object(main, "run_command", return_value=0) as run:
            main.run_streamlit()
        command = run.call_args[0][0]
        self.assertIn("--server.address", command)
        self.assertIn("0.0.0.0", command)

    def test_local_only_keeps_the_app_on_this_machine(self) -> None:
        import main

        with mock.patch.object(main, "run_command", return_value=0) as run:
            main.run_streamlit(share_on_network=False)
        command = run.call_args[0][0]
        self.assertIn("--server.address", command)
        self.assertIn("127.0.0.1", command)
        self.assertNotIn("0.0.0.0", command)

    def test_local_only_flag_reaches_run_streamlit(self) -> None:
        """The flag must actually change the bind address, not just parse."""
        import main
        import sys as system

        for argv, expected in ((["main.py"], "0.0.0.0"), (["main.py", "--local-only"], "127.0.0.1")):
            with mock.patch.object(system, "argv", argv):
                args = main.parse_args()
            with mock.patch.object(main, "run_command", return_value=0) as run:
                main.run_streamlit(share_on_network=not args.local_only)
            self.assertIn(expected, run.call_args[0][0], argv)


if __name__ == "__main__":
    unittest.main()
