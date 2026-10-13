"""Unit tests for the SDN Topology Client.

Tests offline topology saving/loading from JSON files, HTTP request handling,
connection error handling, timeouts, and malformed JSON responses.
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sdn.topology import TopologyClient


class TestSDNTopologyClient(unittest.TestCase):
    """Tests for TopologyClient file persistence and REST API interaction."""

    def setUp(self) -> None:
        """Create a client instance with standard test configuration."""
        self.client = TopologyClient(base_url="http://127.0.0.1:8080", timeout=1.0)
        self.sample_topology = {
            "switches": [
                {
                    "dpid": "0000000000000001",
                    "ports": [{"port_no": 1}, {"port_no": 2}],
                }
            ],
            "links": [
                {
                    "src_dpid": "0000000000000001",
                    "src_port": 1,
                    "dst_dpid": "0000000000000002",
                    "dst_port": 1,
                }
            ],
            "hosts": [
                {
                    "mac": "00:00:00:00:00:01",
                    "ipv4": ["10.0.0.1"],
                    "dpid": "0000000000000001",
                    "port": 2,
                }
            ],
        }

    def test_save_and_load_topology(self) -> None:
        """Verify saving topology to a JSON file and loading it back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test_topo.json")

            # Save topology
            save_success = self.client.save_topology(file_path, self.sample_topology)
            self.assertTrue(save_success)
            self.assertTrue(os.path.exists(file_path))

            # Load topology
            loaded_data = TopologyClient.load_topology(file_path)
            self.assertEqual(len(loaded_data["switches"]), 1)
            self.assertEqual(len(loaded_data["links"]), 1)
            self.assertEqual(len(loaded_data["hosts"]), 1)
            self.assertEqual(loaded_data["switches"][0]["dpid"], "0000000000000001")
            self.assertEqual(loaded_data["hosts"][0]["ipv4"], ["10.0.0.1"])

    def test_load_topology_nonexistent_file(self) -> None:
        """Verify load_topology returns empty structures if file does not exist."""
        result = TopologyClient.load_topology("/nonexistent/path/topo.json")
        self.assertEqual(result, {"switches": [], "links": [], "hosts": []})

    def test_load_topology_malformed_json(self) -> None:
        """Verify load_topology handles malformed JSON files gracefully."""
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("INVALID_JSON_CONTENT{{{")
            tf_path = tf.name

        try:
            result = TopologyClient.load_topology(tf_path)
            self.assertEqual(result, {"switches": [], "links": [], "hosts": []})
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_load_topology_non_dict_json(self) -> None:
        """Verify load_topology handles JSON that contains a list instead of dict."""
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            json.dump(["item1", "item2"], tf)
            tf_path = tf.name

        try:
            result = TopologyClient.load_topology(tf_path)
            self.assertEqual(result, {"switches": [], "links": [], "hosts": []})
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("urllib.request.urlopen")
    def test_get_switches_success(self, mock_urlopen: MagicMock) -> None:
        """Verify successful retrieval and parsing of switches list."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps([{"dpid": "0000000000000001"}]).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        switches = self.client.get_switches()
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0]["dpid"], "0000000000000001")

    @patch("urllib.request.urlopen")
    def test_get_links_success(self, mock_urlopen: MagicMock) -> None:
        """Verify successful retrieval and parsing of inter-switch links."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps([
            {"src_dpid": "1", "dst_dpid": "2"}
        ]).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        links = self.client.get_links()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["src_dpid"], "1")

    @patch("urllib.request.urlopen")
    def test_get_hosts_success(self, mock_urlopen: MagicMock) -> None:
        """Verify successful retrieval and parsing of host list."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps([
            {"mac": "00:00:00:00:00:01", "ipv4": ["10.0.0.1"]}
        ]).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        hosts = self.client.get_hosts()
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["mac"], "00:00:00:00:00:01")

    @patch("urllib.request.urlopen")
    def test_get_full_topology_aggregated(self, mock_urlopen: MagicMock) -> None:
        """Verify retrieval when controller implements /topology/full."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(self.sample_topology).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        topo = self.client.get_full_topology()
        self.assertEqual(len(topo["switches"]), 1)
        self.assertEqual(len(topo["links"]), 1)
        self.assertEqual(len(topo["hosts"]), 1)

    @patch("urllib.request.urlopen")
    def test_connection_error_handling(self, mock_urlopen: MagicMock) -> None:
        """Verify URLError (e.g., controller not running) returns empty data gracefully."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        switches = self.client.get_switches()
        self.assertEqual(switches, [])

        links = self.client.get_links()
        self.assertEqual(links, [])

        hosts = self.client.get_hosts()
        self.assertEqual(hosts, [])

    @patch("urllib.request.urlopen")
    def test_timeout_handling(self, mock_urlopen: MagicMock) -> None:
        """Verify TimeoutError returns empty list gracefully."""
        mock_urlopen.side_effect = TimeoutError("Request timed out")

        switches = self.client.get_switches()
        self.assertEqual(switches, [])

    @patch("urllib.request.urlopen")
    def test_http_error_handling(self, mock_urlopen: MagicMock) -> None:
        """Verify HTTP 404 or 500 error returns empty list."""
        import io
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/topology/switches",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=io.BytesIO(b""),
        )

        switches = self.client.get_switches()
        self.assertEqual(switches, [])

    @patch("urllib.request.urlopen")
    def test_malformed_json_response_from_controller(self, mock_urlopen: MagicMock) -> None:
        """Verify malformed JSON from controller endpoint returns empty list."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"<html>502 Bad Gateway</html>"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        switches = self.client.get_switches()
        self.assertEqual(switches, [])


if __name__ == "__main__":
    unittest.main()
