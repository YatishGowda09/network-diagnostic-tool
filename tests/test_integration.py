"""End-to-end integration test for the network diagnostic tool.

Tests live loopback UDP socket communication between UDPServer and UDPClient,
verifying packet transmission, echo round-trip timing, zero packet loss over
loopback, and end-to-end reporting.

No root privileges, Mininet, or Ryu controller required.
"""

import json
import os
import sys
import threading
import time
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.report import generate_report
from src.diagnostic.udp_client import UDPClient
from src.diagnostic.udp_server import UDPServer


class TestLoopbackIntegration(unittest.TestCase):
    """Live loopback socket integration tests.

    Verifies that the UDP client and server communicate properly over
    the local loopback interface (127.0.0.1) using real OS networking sockets.
    """

    TEST_HOST: str = "127.0.0.1"
    TEST_PORT: int = 15005
    PROBE_COUNT: int = 5
    PROBE_INTERVAL: float = 0.1
    PROBE_TIMEOUT: float = 1.0

    def setUp(self) -> None:
        """Initialize and launch the UDPServer in a daemon background thread."""
        self.server = UDPServer(host=self.TEST_HOST, port=self.TEST_PORT)

        # Threading note: The server runs in a daemon thread so it terminates
        # automatically when tests finish.
        self.server_thread = threading.Thread(
            target=self.server.run,
            name="UDPServerIntegrationThread",
            daemon=True,
        )
        self.server_thread.start()

        # Wait until the server socket has successfully bound and is ready to receive
        deadline = time.time() + 2.0
        while self.server._sock is None and time.time() < deadline:
            time.sleep(0.02)

        self.assertIsNotNone(
            self.server._sock,
            "UDPServer socket failed to initialize within deadline",
        )

    def tearDown(self) -> None:
        """Close the server socket to stop the loop and wait for thread to join."""
        if self.server._sock:
            try:
                # Closing the socket causes recvfrom() in the server loop to raise
                # an OSError, gracefully breaking the infinite receive loop.
                self.server._sock.close()
            except OSError:
                pass

        self.server_thread.join(timeout=1.0)

    def test_udp_client_server_loopback_communication(self) -> None:
        """Send 5 real UDP probes over 127.0.0.1 and verify 0% loss and fast RTT."""
        # 1. Initialize client configured to probe the local server
        client = UDPClient(
            target=self.TEST_HOST,
            port=self.TEST_PORT,
            count=self.PROBE_COUNT,
            timeout=self.PROBE_TIMEOUT,
            interval=self.PROBE_INTERVAL,
        )

        # 2. Execute diagnostic run against the active UDP server
        stats = client.run()

        # 3. Assert probe counts
        self.assertEqual(
            stats["probes_sent"],
            self.PROBE_COUNT,
            f"Expected {self.PROBE_COUNT} probes sent, got {stats['probes_sent']}",
        )
        self.assertEqual(
            stats["responses_received"],
            self.PROBE_COUNT,
            f"Expected {self.PROBE_COUNT} responses, got {stats['responses_received']}",
        )

        # 4. Loopback communication on localhost must have 0% packet loss
        self.assertEqual(
            stats["packet_loss_percent"],
            0.0,
            f"Expected 0% packet loss on loopback, got {stats['packet_loss_percent']}%",
        )

        # 5. Round trip time over OS loopback interface should be well below 50ms
        self.assertIsNotNone(stats["rtt_min_ms"])
        self.assertIsNotNone(stats["rtt_avg_ms"])
        self.assertIsNotNone(stats["rtt_max_ms"])

        self.assertLess(
            stats["rtt_avg_ms"],
            50.0,
            f"Loopback average RTT ({stats['rtt_avg_ms']}ms) exceeded 50ms threshold",
        )
        self.assertLess(
            stats["rtt_max_ms"],
            50.0,
            f"Loopback max RTT ({stats['rtt_max_ms']}ms) exceeded 50ms threshold",
        )
        self.assertGreaterEqual(
            stats["rtt_min_ms"],
            0.0,
            "RTT cannot be negative",
        )

        # 6. Verify individual probe records are well-structured
        self.assertEqual(len(stats["individual_results"]), self.PROBE_COUNT)
        for seq_idx, probe_result in enumerate(stats["individual_results"], 1):
            self.assertEqual(probe_result["seq"], seq_idx)
            self.assertEqual(probe_result["status"], "success")
            self.assertIsNone(probe_result["error"])
            self.assertIsNotNone(probe_result["rtt_ms"])
            self.assertIsNotNone(probe_result["server_timestamp"])

        # 7. Verify UDPServer recorded all incoming probes
        self.assertGreaterEqual(self.server.total_probes_received, self.PROBE_COUNT)

    def test_full_pipeline_with_report_generation(self) -> None:
        """Verify client statistics integrate seamlessly with report generation."""
        client = UDPClient(
            target=self.TEST_HOST,
            port=self.TEST_PORT,
            count=3,
            timeout=1.0,
            interval=0.05,
        )
        client_stats = client.run()

        synthetic_topology = {
            "switches": [
                {"dpid": "0000000000000001", "ports": [{"port_no": 1}, {"port_no": 2}]},
                {"dpid": "0000000000000002", "ports": [{"port_no": 1}, {"port_no": 2}]},
            ],
            "links": [
                {"src_dpid": "0000000000000001", "src_port": 1, "dst_dpid": "0000000000000002", "dst_port": 1},
            ],
            "hosts": [
                {"mac": "00:00:00:00:00:01", "ipv4": ["127.0.0.1"], "dpid": "0000000000000001", "port": 2},
                {"mac": "00:00:00:00:00:02", "ipv4": ["127.0.0.2"], "dpid": "0000000000000002", "port": 2},
            ],
        }

        report = generate_report(
            diagnostic_results=client_stats,
            topology_data=synthetic_topology,
            source_ip="127.0.0.1",
            dest_ip="127.0.0.2",
        )

        report_json = json.loads(report.to_json())
        self.assertEqual(report_json["source_ip"], "127.0.0.1")
        self.assertEqual(report_json["dest_ip"], "127.0.0.2")
        self.assertEqual(len(report_json["candidate_paths"]), 1)
        self.assertEqual(len(report_json["disclaimers"]), 2)


if __name__ == "__main__":
    unittest.main()
