"""Unit tests for the network topology graph and path analysis module.

Tests graph construction, BFS shortest path discovery, DFS all-paths
enumeration, disconnected graphs, edge cases, and SDN topology ingestion.
"""

import os
import sys
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.path_analysis import PathResult, TopologyGraph


class TestTopologyGraphPathAnalysis(unittest.TestCase):
    """Tests for path discovery algorithms on network graphs."""

    def setUp(self) -> None:
        r"""Set up a canonical Diamond topology for path testing.

        Diamond topology structure:
             h1 (10.0.0.1)
                 |
                s1
               /  \
             s2    s3
               \  /
                s4
                 |
             h2 (10.0.0.2)
        """
        self.graph = TopologyGraph()
        self.s1 = "0000000000000001"
        self.s2 = "0000000000000002"
        self.s3 = "0000000000000003"
        self.s4 = "0000000000000004"

        # Inter-switch links
        self.graph.add_link(self.s1, 1, self.s2, 1)
        self.graph.add_link(self.s1, 2, self.s3, 1)
        self.graph.add_link(self.s2, 2, self.s4, 1)
        self.graph.add_link(self.s3, 2, self.s4, 2)

        # Host attachments
        self.graph.add_host("h1", "00:00:00:00:00:01", "10.0.0.1", self.s1, 3)
        self.graph.add_host("h2", "00:00:00:00:00:02", "10.0.0.2", self.s4, 3)

    def test_find_all_paths_diamond_topology(self) -> None:
        """Verify DFS identifies exactly 2 equal-length paths between h1 and h2."""
        paths = self.graph.find_all_paths("h1", "h2")

        self.assertEqual(len(paths), 2)
        path_nodes = [p.path for p in paths]

        expected_path_1 = ["h1", self.s1, self.s2, self.s4, "h2"]
        expected_path_2 = ["h1", self.s1, self.s3, self.s4, "h2"]

        self.assertIn(expected_path_1, path_nodes)
        self.assertIn(expected_path_2, path_nodes)

        # In diamond topology, both paths have hop count 4
        for p in paths:
            self.assertEqual(p.length, 4)
            self.assertTrue(p.is_shortest)

    def test_find_shortest_path_diamond_topology(self) -> None:
        """Verify BFS returns a valid shortest path between h1 and h2."""
        shortest = self.graph.find_shortest_path("h1", "h2")

        self.assertIsNotNone(shortest)
        self.assertEqual(shortest.length, 4)
        self.assertTrue(shortest.is_shortest)
        self.assertEqual(shortest.path[0], "h1")
        self.assertEqual(shortest.path[-1], "h2")
        self.assertIn(shortest.path[2], [self.s2, self.s3])

    def test_asymmetric_path_lengths(self) -> None:
        """Verify shortest path flag correctly identifies shorter route."""
        # Add a direct shortcut link between s1 and s4
        self.graph.add_link(self.s1, 4, self.s4, 4)

        paths = self.graph.find_all_paths("h1", "h2")
        self.assertEqual(len(paths), 3)

        shortest = self.graph.find_shortest_path("h1", "h2")
        self.assertIsNotNone(shortest)
        self.assertEqual(shortest.length, 3)
        self.assertEqual(shortest.path, ["h1", self.s1, self.s4, "h2"])

    def test_disconnected_nodes(self) -> None:
        """Verify behavior when destination is unreachable (isolated component)."""
        isolated_switch = self.graph.add_switch("0000000000000099")
        self.graph.add_host("h_isolated", "00:00:00:00:00:99", "10.0.0.99", isolated_switch, 1)

        paths = self.graph.find_all_paths("h1", "h_isolated")
        self.assertEqual(paths, [])

        shortest = self.graph.find_shortest_path("h1", "h_isolated")
        self.assertIsNone(shortest)

    def test_single_node_same_source_and_destination(self) -> None:
        """Verify zero-length path returned when source and destination are the same."""
        paths = self.graph.find_all_paths("h1", "h1")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].path, ["h1"])
        self.assertEqual(paths[0].length, 0)
        self.assertTrue(paths[0].is_shortest)

        shortest = self.graph.find_shortest_path("h1", "h1")
        self.assertIsNotNone(shortest)
        self.assertEqual(shortest.path, ["h1"])
        self.assertEqual(shortest.length, 0)

    def test_empty_graph(self) -> None:
        """Verify empty graph returns empty paths without exception."""
        empty_graph = TopologyGraph()

        self.assertEqual(empty_graph.find_all_paths("s1", "s2"), [])
        self.assertIsNone(empty_graph.find_shortest_path("s1", "s2"))
        self.assertEqual(empty_graph.get_paths_between_hosts("10.0.0.1", "10.0.0.2"), [])

    def test_nonexistent_node_lookup(self) -> None:
        """Verify queries for nonexistent node identifiers return empty results."""
        self.assertEqual(self.graph.find_all_paths("nonexistent_a", "h2"), [])
        self.assertEqual(self.graph.find_all_paths("h1", "nonexistent_b"), [])
        self.assertIsNone(self.graph.find_shortest_path("h1", "nonexistent_b"))

    def test_get_paths_between_hosts_by_ip(self) -> None:
        """Verify IP-to-host resolution and candidate path discovery."""
        paths = self.graph.get_paths_between_hosts("10.0.0.1", "10.0.0.2")
        self.assertEqual(len(paths), 2)
        for p in paths:
            self.assertEqual(p.path[0], "h1")
            self.assertEqual(p.path[-1], "h2")

        # Unknown IP returns empty list
        self.assertEqual(self.graph.get_paths_between_hosts("10.0.0.1", "192.168.1.1"), [])

    def test_build_from_topology_data(self) -> None:
        """Verify graph construction from structured topology dictionary."""
        sample_data = {
            "switches": [
                {"dpid": 1, "ports": [{"port_no": 1}, {"port_no": 2}]},
                {"dpid": 2, "ports": [{"port_no": 1}, {"port_no": 2}]},
            ],
            "links": [
                {"src_dpid": 1, "src_port": 1, "dst_dpid": 2, "dst_port": 1},
            ],
            "hosts": [
                {"host_id": "h1", "mac": "00:00:00:00:00:01", "ipv4": ["10.0.0.1"], "dpid": 1, "port": 2},
                {"host_id": "h2", "mac": "00:00:00:00:00:02", "ipv4": ["10.0.0.2"], "dpid": 2, "port": 2},
            ],
        }

        new_graph = TopologyGraph()
        new_graph.build_from_topology_data(sample_data)

        norm_s1 = "0000000000000001"
        norm_s2 = "0000000000000002"

        self.assertIn(norm_s1, new_graph.switches)
        self.assertIn(norm_s2, new_graph.switches)
        self.assertIn("h1", new_graph.hosts)
        self.assertIn("h2", new_graph.hosts)

        paths = new_graph.get_paths_between_hosts("10.0.0.1", "10.0.0.2")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].path, ["h1", norm_s1, norm_s2, "h2"])
        self.assertEqual(paths[0].length, 3)


if __name__ == "__main__":
    unittest.main()
