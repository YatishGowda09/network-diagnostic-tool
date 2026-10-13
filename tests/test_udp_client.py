"""Unit tests for the UDP diagnostic client.

Tests probe message creation, response parsing, RTT statistics calculation,
packet loss formulas, duplicate packet handling, and malformed packet detection.
"""

import json
import os
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.diagnostic.udp_client import UDPClient


class TestUDPClientMessageFormat(unittest.TestCase):
    """Tests for UDP probe message construction and parsing."""

    def setUp(self) -> None:
        """Create a default client instance for testing."""
        self.client = UDPClient(target="127.0.0.1", port=5005, count=5, timeout=1.0)

    def test_probe_payload_creation(self) -> None:
        """Verify probe payload contains required JSON fields and types."""
        seq = 1
        raw_payload = self.client.build_probe_payload(seq)

        # Datagram payloads sent over UDP are serialized as raw bytes
        self.assertIsInstance(raw_payload, bytes)
        decoded = json.loads(raw_payload.decode("utf-8"))

        self.assertEqual(decoded["type"], "probe")
        self.assertEqual(decoded["seq"], seq)
        self.assertIn("timestamp", decoded)
        self.assertIsInstance(decoded["timestamp"], (int, float))
        self.assertEqual(decoded["payload"], "DIAG")

    def test_parse_valid_response(self) -> None:
        """Verify successful parsing of a valid echo response."""
        echo_message = {
            "type": "echo",
            "seq": 42,
            "timestamp": 1000.0,
            "server_timestamp": 1000.005,
            "payload": "DIAG",
        }
        raw_bytes = json.dumps(echo_message).encode("utf-8")
        parsed = self.client.parse_response(raw_bytes)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["type"], "echo")
        self.assertEqual(parsed["seq"], 42)
        self.assertEqual(parsed["timestamp"], 1000.0)
        self.assertEqual(parsed["server_timestamp"], 1000.005)

    def test_parse_malformed_json(self) -> None:
        """Verify that malformed/corrupted JSON payloads return None gracefully."""
        corrupted_bytes = b"NOT_VALID_JSON{:::}"
        parsed = self.client.parse_response(corrupted_bytes)
        self.assertIsNone(parsed)

    def test_parse_invalid_unicode(self) -> None:
        """Verify handling of invalid non-UTF-8 bytes."""
        invalid_bytes = b"\xff\xfe\xfa\xfb"
        parsed = self.client.parse_response(invalid_bytes)
        self.assertIsNone(parsed)

    def test_parse_non_dict_json(self) -> None:
        """Verify that JSON primitives/arrays return None (expecting object)."""
        json_array = json.dumps([1, 2, 3]).encode("utf-8")
        parsed = self.client.parse_response(json_array)
        self.assertIsNone(parsed)

    def test_parse_wrong_message_type(self) -> None:
        """Verify that messages with unexpected type (not 'echo') are rejected."""
        wrong_type = {
            "type": "probe",
            "seq": 1,
            "timestamp": 100.0,
        }
        parsed = self.client.parse_response(json.dumps(wrong_type).encode("utf-8"))
        self.assertIsNone(parsed)

    def test_parse_missing_sequence(self) -> None:
        """Verify rejection when sequence number is missing or not an int."""
        missing_seq = {
            "type": "echo",
            "timestamp": 100.0,
        }
        parsed = self.client.parse_response(json.dumps(missing_seq).encode("utf-8"))
        self.assertIsNone(parsed)

        invalid_seq_type = {
            "type": "echo",
            "seq": "not-an-integer",
            "timestamp": 100.0,
        }
        parsed = self.client.parse_response(json.dumps(invalid_seq_type).encode("utf-8"))
        self.assertIsNone(parsed)


class TestUDPClientStatistics(unittest.TestCase):
    """Tests for round-trip time and packet loss statistical calculations."""

    def setUp(self) -> None:
        """Create client for statistics testing."""
        self.client = UDPClient(target="127.0.0.1", port=5005)

    def test_packet_loss_partial(self) -> None:
        """Verify 10 sent, 8 received equals 20.0% packet loss."""
        self.client.probes_sent = 10
        self.client.responses_received = 8
        stats = self.client.calculate_statistics()
        self.assertEqual(stats["packet_loss_percent"], 20.0)

    def test_packet_loss_zero_sent(self) -> None:
        """Verify 0 sent equals 0.0% loss with no ZeroDivisionError."""
        self.client.probes_sent = 0
        self.client.responses_received = 0
        stats = self.client.calculate_statistics()
        self.assertEqual(stats["packet_loss_percent"], 0.0)

    def test_packet_loss_all_received(self) -> None:
        """Verify 10 sent, 10 received equals 0.0% loss."""
        self.client.probes_sent = 10
        self.client.responses_received = 10
        stats = self.client.calculate_statistics()
        self.assertEqual(stats["packet_loss_percent"], 0.0)

    def test_packet_loss_none_received(self) -> None:
        """Verify 10 sent, 0 received equals 100.0% loss."""
        self.client.probes_sent = 10
        self.client.responses_received = 0
        stats = self.client.calculate_statistics()
        self.assertEqual(stats["packet_loss_percent"], 100.0)

    def test_rtt_statistics(self) -> None:
        """Verify min, max, and avg RTT calculation from recorded samples."""
        self.client.probes_sent = 3
        self.client.responses_received = 3
        self.client.rtt_records = [10.5, 20.5, 15.0]

        stats = self.client.calculate_statistics()
        self.assertAlmostEqual(stats["rtt_min_ms"], 10.5, places=2)
        self.assertAlmostEqual(stats["rtt_max_ms"], 20.5, places=2)
        self.assertAlmostEqual(stats["rtt_avg_ms"], 15.333, places=2)

    def test_rtt_statistics_when_no_responses(self) -> None:
        """Verify RTT stats are None when all packets are lost."""
        self.client.probes_sent = 5
        self.client.responses_received = 0
        self.client.rtt_records = []

        stats = self.client.calculate_statistics()
        self.assertIsNone(stats["rtt_min_ms"])
        self.assertIsNone(stats["rtt_max_ms"])
        self.assertIsNone(stats["rtt_avg_ms"])


class TestUDPClientSocketHandling(unittest.TestCase):
    """Tests for socket send/receive routines with mocked network layer."""

    def setUp(self) -> None:
        self.client = UDPClient(target="127.0.0.1", port=5005, timeout=0.5)

    def test_send_probe_success(self) -> None:
        """Verify successful probe transmission and response parsing."""
        mock_sock = MagicMock(spec=socket.socket)
        echo_resp = {
            "type": "echo",
            "seq": 1,
            "timestamp": 100.0,
            "server_timestamp": 100.002,
            "payload": "DIAG",
        }
        mock_sock.recvfrom.return_value = (json.dumps(echo_resp).encode("utf-8"), ("127.0.0.1", 5005))

        result = self.client.send_probe(mock_sock, seq=1)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["seq"], 1)
        self.assertIsNotNone(result["rtt_ms"])
        self.assertEqual(self.client.responses_received, 1)
        self.assertIn(1, self.client.seen_sequences)

    def test_send_probe_timeout(self) -> None:
        """Verify socket timeout exception is handled cleanly."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recvfrom.side_effect = socket.timeout()

        result = self.client.send_probe(mock_sock, seq=2)

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["seq"], 2)
        self.assertIsNone(result["rtt_ms"])
        self.assertEqual(self.client.responses_received, 0)

    def test_duplicate_response_detection(self) -> None:
        """Verify duplicate responses for the same sequence number are ignored."""
        mock_sock = MagicMock(spec=socket.socket)
        echo_resp_dup = {
            "type": "echo",
            "seq": 1,
            "timestamp": 100.0,
            "server_timestamp": 100.002,
        }
        echo_resp_expected = {
            "type": "echo",
            "seq": 2,
            "timestamp": 100.0,
            "server_timestamp": 100.002,
        }

        # Sequence 1 is already in seen_sequences
        self.client.seen_sequences.add(1)

        # recvfrom first returns duplicate seq 1, then returns expected seq 2
        mock_sock.recvfrom.side_effect = [
            (json.dumps(echo_resp_dup).encode("utf-8"), ("127.0.0.1", 5005)),
            (json.dumps(echo_resp_expected).encode("utf-8"), ("127.0.0.1", 5005)),
        ]

        result = self.client.send_probe(mock_sock, seq=2)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["seq"], 2)
        self.assertIn(2, self.client.seen_sequences)
        # Responses received should only increment for the new successful response
        self.assertEqual(self.client.responses_received, 1)

    def test_out_of_order_response_handling(self) -> None:
        """Verify that late packets with wrong sequence are recorded and loop continues."""
        mock_sock = MagicMock(spec=socket.socket)
        late_resp = {
            "type": "echo",
            "seq": 99,
            "timestamp": 100.0,
            "server_timestamp": 100.002,
        }
        matching_resp = {
            "type": "echo",
            "seq": 3,
            "timestamp": 100.0,
            "server_timestamp": 100.002,
        }

        mock_sock.recvfrom.side_effect = [
            (json.dumps(late_resp).encode("utf-8"), ("127.0.0.1", 5005)),
            (json.dumps(matching_resp).encode("utf-8"), ("127.0.0.1", 5005)),
        ]

        result = self.client.send_probe(mock_sock, seq=3)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["seq"], 3)
        self.assertIn(99, self.client.seen_sequences)
        self.assertIn(3, self.client.seen_sequences)


if __name__ == "__main__":
    unittest.main()
