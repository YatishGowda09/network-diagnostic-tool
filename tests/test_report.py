"""Unit tests for the integrated diagnostic and topology reporting module.

Tests text and JSON report generation, formatting of RTT and packet loss
statistics, inclusion of mandatory engineering disclaimers, and resilience to
empty or missing diagnostic and topology datasets.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.report import (
    DISCLAIMER_FORWARDING_PATH,
    DISCLAIMER_RTT_MEASUREMENTS,
    DiagnosticReport,
    generate_report,
)


class TestDiagnosticReport(unittest.TestCase):
    """Tests for report generation and output serialization."""

    def setUp(self) -> None:
        """Create sample diagnostic and topology inputs for tests."""
        self.sample_diag = {
            "packets_sent": 10,
            "packets_received": 9,
            "packet_loss_pct": 10.0,
            "rtt_min_ms": 1.25,
            "rtt_avg_ms": 2.40,
            "rtt_max_ms": 3.80,
            "rtt_mdev_ms": 0.55,
        }

        self.sample_topo = {
            "switches": [
                {"dpid": "0000000000000001", "ports": [{"port_no": 1}, {"port_no": 2}]},
                {"dpid": "0000000000000002", "ports": [{"port_no": 1}, {"port_no": 2}]},
            ],
            "links": [
                {"src_dpid": "0000000000000001", "src_port": 1, "dst_dpid": "0000000000000002", "dst_port": 1},
            ],
            "hosts": [
                {"mac": "00:00:00:00:00:01", "ipv4": ["10.0.0.1"], "dpid": "0000000000000001", "port": 2},
                {"mac": "00:00:00:00:00:02", "ipv4": ["10.0.0.2"], "dpid": "0000000000000002", "port": 2},
            ],
        }

    def test_generate_report_basic(self) -> None:
        """Verify report creation with valid diagnostic and topology data."""
        report = generate_report(
            diagnostic_results=self.sample_diag,
            topology_data=self.sample_topo,
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        self.assertIsInstance(report, DiagnosticReport)
        self.assertEqual(report.source_ip, "10.0.0.1")
        self.assertEqual(report.dest_ip, "10.0.0.2")
        self.assertEqual(len(report.candidate_paths), 1)
        self.assertEqual(report.candidate_paths[0].length, 3)

    def test_report_includes_required_disclaimers(self) -> None:
        """Verify report explicitly includes SDN forwarding and RTT disclaimers."""
        report = generate_report(
            diagnostic_results=self.sample_diag,
            topology_data=self.sample_topo,
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        # Check in dictionary representation
        report_dict = report.to_dict()
        self.assertIn("disclaimers", report_dict)
        self.assertIn(DISCLAIMER_FORWARDING_PATH, report_dict["disclaimers"])
        self.assertIn(DISCLAIMER_RTT_MEASUREMENTS, report_dict["disclaimers"])

        # Check in rendered text representation
        text_output = report.to_text()
        self.assertIn(DISCLAIMER_FORWARDING_PATH, text_output)
        self.assertIn(DISCLAIMER_RTT_MEASUREMENTS, text_output)

    def test_report_json_output_format(self) -> None:
        """Verify JSON representation is valid JSON and contains all required keys."""
        report = generate_report(
            diagnostic_results=self.sample_diag,
            topology_data=self.sample_topo,
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        json_str = report.to_json()
        parsed = json.loads(json_str)

        expected_keys = {
            "source_ip",
            "dest_ip",
            "diagnostic_summary",
            "topology_summary",
            "candidate_paths",
            "disclaimers",
        }
        self.assertTrue(expected_keys.issubset(set(parsed.keys())))
        self.assertEqual(parsed["source_ip"], "10.0.0.1")
        self.assertEqual(parsed["dest_ip"], "10.0.0.2")
        self.assertEqual(parsed["diagnostic_summary"]["packets_sent"], 10)

    def test_report_with_empty_topology_data(self) -> None:
        """Verify report generation handles empty topology gracefully."""
        report = generate_report(
            diagnostic_results=self.sample_diag,
            topology_data={},
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        self.assertEqual(len(report.candidate_paths), 0)
        text_output = report.to_text()
        self.assertIn("No candidate paths found", text_output)
        self.assertIn("Switches (0 discovered)", text_output)

    def test_report_with_empty_diagnostic_data(self) -> None:
        """Verify report generation handles empty diagnostic results without raising error."""
        report = generate_report(
            diagnostic_results={},
            topology_data=self.sample_topo,
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        text_output = report.to_text()
        self.assertIn("Packets:      Sent = N/A, Received = N/A", text_output)
        self.assertIn("Min = N/A, Avg = N/A", text_output)

    def test_report_save_methods(self) -> None:
        """Verify report save method for text and JSON file formats."""
        report = generate_report(
            diagnostic_results=self.sample_diag,
            topology_data=self.sample_topo,
            source_ip="10.0.0.1",
            dest_ip="10.0.0.2",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            text_file = os.path.join(tmpdir, "report.txt")
            json_file = os.path.join(tmpdir, "report.json")

            # Test text saving
            report.save(text_file, output_format="text")
            self.assertTrue(os.path.exists(text_file))
            with open(text_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("INTEGRATED NETWORK DIAGNOSTIC & PATH REPORT", content)

            # Test JSON saving
            report.save(json_file, output_format="json")
            self.assertTrue(os.path.exists(json_file))
            with open(json_file, "r", encoding="utf-8") as f:
                saved_json = json.load(f)
                self.assertEqual(saved_json["source_ip"], "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
