"""Unit tests for the UDP diagnostic server.

Tests incoming probe validation, parsing of malformed packets, rejection
of non-probe message types, and construction of compliant echo responses.
"""

import json
import os
import sys
import time
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.diagnostic.udp_server import UDPServer


class TestUDPServerMessageHandling(unittest.TestCase):
    """Tests for UDP server packet handling and response generation."""

    def setUp(self) -> None:
        """Create a UDPServer instance for testing logic."""
        self.server = UDPServer(host="127.0.0.1", port=5005)

    def test_parse_valid_probe(self) -> None:
        """Verify server parses a well-formed probe packet successfully."""
        probe_data = {
            "type": "probe",
            "seq": 10,
            "timestamp": 123456.789,
            "payload": "DIAG",
        }
        raw_bytes = json.dumps(probe_data).encode("utf-8")
        parsed = self.server.parse_probe(raw_bytes)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["type"], "probe")
        self.assertEqual(parsed["seq"], 10)
        self.assertEqual(parsed["timestamp"], 123456.789)
        self.assertEqual(parsed.get("payload"), "DIAG")

    def test_build_echo_response(self) -> None:
        """Verify server builds a valid echo response retaining probe metadata."""
        probe = {
            "type": "probe",
            "seq": 5,
            "timestamp": 1000.5,
            "payload": "CUSTOM_DATA",
        }

        t_before = time.time()
        resp_bytes = self.server.build_response(probe)
        t_after = time.time()

        self.assertIsInstance(resp_bytes, bytes)
        decoded = json.loads(resp_bytes.decode("utf-8"))

        self.assertEqual(decoded["type"], "echo")
        self.assertEqual(decoded["seq"], 5)
        self.assertEqual(decoded["timestamp"], 1000.5)
        self.assertEqual(decoded["payload"], "CUSTOM_DATA")
        self.assertIn("server_timestamp", decoded)
        self.assertTrue(t_before <= decoded["server_timestamp"] <= t_after)

    def test_build_echo_response_default_payload(self) -> None:
        """Verify fallback to 'DIAG' payload if probe lacks payload field."""
        probe = {
            "type": "probe",
            "seq": 1,
            "timestamp": 2000.0,
        }
        resp_bytes = self.server.build_response(probe)
        decoded = json.loads(resp_bytes.decode("utf-8"))
        self.assertEqual(decoded["payload"], "DIAG")

    def test_ignore_non_probe_messages(self) -> None:
        """Verify server drops packets where type is not 'probe'."""
        non_probe_types = [
            {"type": "echo", "seq": 1, "timestamp": 100.0},
            {"type": "keepalive", "seq": 2, "timestamp": 100.0},
            {"type": "dns_query", "seq": 3, "timestamp": 100.0},
            {"seq": 4, "timestamp": 100.0},  # missing type
        ]

        for msg in non_probe_types:
            raw = json.dumps(msg).encode("utf-8")
            self.assertIsNone(
                self.server.parse_probe(raw),
                f"Server should have dropped packet: {msg}",
            )

    def test_parse_malformed_json(self) -> None:
        """Verify server drops malformed JSON strings."""
        malformed_inputs = [
            b"",
            b"{not-valid-json}",
            b'{"type": "probe", "seq": ',
            b"\x00\x01\x02\x03",
        ]
        for bad_bytes in malformed_inputs:
            self.assertIsNone(self.server.parse_probe(bad_bytes))

    def test_parse_non_dict_json(self) -> None:
        """Verify server drops valid JSON that is not an object/dictionary."""
        bad_json_types = [
            json.dumps(["probe", 1, 100.0]).encode("utf-8"),
            json.dumps("some string").encode("utf-8"),
            json.dumps(12345).encode("utf-8"),
            json.dumps(True).encode("utf-8"),
        ]
        for bad_payload in bad_json_types:
            self.assertIsNone(self.server.parse_probe(bad_payload))

    def test_parse_invalid_sequence_number(self) -> None:
        """Verify server rejects probes with missing or non-integer sequence."""
        test_cases = [
            {"type": "probe", "timestamp": 100.0},  # missing seq
            {"type": "probe", "seq": "one", "timestamp": 100.0},  # string seq
            {"type": "probe", "seq": 1.5, "timestamp": 100.0},  # float seq
            {"type": "probe", "seq": None, "timestamp": 100.0},  # None seq
        ]
        for case in test_cases:
            self.assertIsNone(self.server.parse_probe(json.dumps(case).encode("utf-8")))

    def test_parse_invalid_timestamp(self) -> None:
        """Verify server rejects probes with missing or non-numeric timestamp."""
        test_cases = [
            {"type": "probe", "seq": 1},  # missing timestamp
            {"type": "probe", "seq": 1, "timestamp": "now"},  # string timestamp
            {"type": "probe", "seq": 1, "timestamp": None},  # None timestamp
        ]
        for case in test_cases:
            self.assertIsNone(self.server.parse_probe(json.dumps(case).encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
