"""Unit tests for the SDN controller's dynamic rerouting and graph algorithms.

Tests the NetworkGraph topology abstraction, BFS shortest path computation,
link failure detection, dynamic rerouting to alternate paths, link recovery,
host attachment tracking, and DPID normalization.

Requires zero external SDN dependencies or root privileges.
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sdn.controller import NetworkGraph


class TestNetworkGraphRerouting(unittest.TestCase):
    """Test suite for NetworkGraph dynamic path computation and failover."""

    def setUp(self) -> None:
        """Construct standard 4-switch diamond topology:
                 +-------+
             +-->|  s2   |---+
             |   +-------+   |
           +-+-+           +-v-+
           | s1 |           | s4 |
           +-+-+           +-^-+
             |   +-------+   |
             +-->|  s3   |---+
                 +-------+
        """
        self.graph = NetworkGraph()
        # s1: port 1 -> s2 (port 1), port 2 -> s3 (port 1)
        self.graph.add_link(1, 1, 2, 1)
        self.graph.add_link(1, 2, 3, 1)

        # s2: port 2 -> s4 (port 1)
        self.graph.add_link(2, 2, 4, 1)

        # s3: port 2 -> s4 (port 2)
        self.graph.add_link(3, 2, 4, 2)

        # Hosts: h1 on s1:port 3, h2 on s4:port 3
        self.graph.add_host("00:00:00:00:00:01", 1, 3, "10.0.0.1")
        self.graph.add_host("00:00:00:00:00:02", 4, 3, "10.0.0.2")

    def test_initial_diamond_shortest_path(self) -> None:
        """Verify BFS returns a valid 2-hop switch path from s1 to s4."""
        path = self.graph.shortest_path(1, 4)
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0], 1)
        self.assertEqual(path[-1], 4)
        # In a symmetric diamond, sorted neighbor order selects s2 first
        self.assertEqual(path, [1, 2, 4])

    def test_dynamic_reroute_on_link_failure(self) -> None:
        """Verify removing link s1-s2 causes immediate dynamic reroute via s3."""
        # Baseline path is through s2
        self.assertEqual(self.graph.shortest_path(1, 4), [1, 2, 4])

        # Simulate link failure on upper branch
        removed = self.graph.remove_link(1, 2)
        self.assertTrue(removed)

        # Rerouted path must now automatically traverse lower branch [s1 -> s3 -> s4]
        new_path = self.graph.shortest_path(1, 4)
        self.assertEqual(new_path, [1, 3, 4])

        # Reverse direction must also dynamically reroute
        reverse_path = self.graph.shortest_path(4, 1)
        self.assertEqual(reverse_path, [4, 3, 1])

    def test_link_recovery_restores_primary_path(self) -> None:
        """Verify restoring link s1-s2 restores the preferred primary path."""
        # 1. Break link s1-s2
        self.graph.remove_link(1, 2)
        self.assertEqual(self.graph.shortest_path(1, 4), [1, 3, 4])

        # 2. Restore link s1-s2
        self.graph.add_link(1, 1, 2, 1)
        recovered_path = self.graph.shortest_path(1, 4)
        self.assertEqual(recovered_path, [1, 2, 4])

    def test_complete_network_partition(self) -> None:
        """Verify empty path is returned when all alternative paths fail."""
        # Remove both branches of the diamond
        self.graph.remove_link(1, 2)
        self.graph.remove_link(1, 3)

        path = self.graph.shortest_path(1, 4)
        self.assertEqual(path, [])

    def test_same_source_and_destination(self) -> None:
        """Verify shortest path to self returns single node."""
        path = self.graph.shortest_path(1, 1)
        self.assertEqual(path, [1])

    def test_unknown_node_lookup(self) -> None:
        """Verify querying non-existent switches returns empty list gracefully."""
        self.assertEqual(self.graph.shortest_path(1, 999), [])
        self.assertEqual(self.graph.shortest_path(888, 4), [])
        self.assertEqual(self.graph.shortest_path(888, 999), [])

    def test_all_paths_in_diamond(self) -> None:
        """Verify all simple loop-free paths are discovered."""
        paths = self.graph.all_paths(1, 4)
        self.assertEqual(len(paths), 2)
        self.assertIn([1, 2, 4], paths)
        self.assertIn([1, 3, 4], paths)

    def test_get_out_port(self) -> None:
        """Verify correct egress port lookup between adjacent switches."""
        # s1 -> s2 uses s1 port 1
        self.assertEqual(self.graph.get_out_port(1, 2), 1)
        # s2 -> s1 uses s2 port 1
        self.assertEqual(self.graph.get_out_port(2, 1), 1)
        # s1 -> s3 uses s1 port 2
        self.assertEqual(self.graph.get_out_port(1, 3), 2)
        # s2 -> s4 uses s2 port 2
        self.assertEqual(self.graph.get_out_port(2, 4), 2)
        # Non-adjacent switches return None
        self.assertIsNone(self.graph.get_out_port(1, 4))

    def test_dpid_normalization(self) -> None:
        """Verify DPID normalization supports ints, hex strings, and padded strings."""
        self.assertEqual(self.graph._normalize_dpid(1), 1)
        self.assertEqual(self.graph._normalize_dpid("1"), 1)
        self.assertEqual(self.graph._normalize_dpid("0x1"), 1)
        self.assertEqual(self.graph._normalize_dpid("0000000000000001"), 1)
        self.assertEqual(self.graph._normalize_dpid("0x000000000000000a"), 10)

        # Path lookup with hex string DPIDs should work identically
        path = self.graph.shortest_path("0000000000000001", "0000000000000004")
        self.assertEqual(path, [1, 2, 4])

    def test_host_registration_and_switch_removal(self) -> None:
        """Verify host tracking and cleanup upon switch removal."""
        self.assertIn("00:00:00:00:00:01", self.graph.hosts)
        self.assertEqual(self.graph.hosts["00:00:00:00:00:01"]["dpid"], 1)

        # Remove switch s1
        self.graph.remove_switch(1)
        self.assertNotIn(1, self.graph.adj)
        # s2 should no longer have s1 as neighbor
        self.assertNotIn(1, self.graph.adj[2])
        # Attached host on s1 should be removed
        self.assertNotIn("00:00:00:00:00:01", self.graph.hosts)
        # Host on s4 remains
        self.assertIn("00:00:00:00:00:02", self.graph.hosts)


if __name__ == "__main__":
    unittest.main()
