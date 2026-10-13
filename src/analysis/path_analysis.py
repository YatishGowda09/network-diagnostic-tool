"""Graph-based network path analysis module.

This module builds an in-memory graph representation of SDN/Mininet network topologies
using Python's standard library and provides path discovery algorithms (BFS/DFS) to
determine all candidate forwarding paths and shortest paths between switches and hosts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class PathResult:
    """Represents a discovered candidate path between two network nodes."""

    path: List[str]
    length: int
    is_shortest: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert path result to dictionary format."""
        return {
            "path": self.path,
            "length": self.length,
            "is_shortest": self.is_shortest,
        }


@dataclass
class HostNode:
    """Metadata describing a network host attached to a switch."""

    host_id: str
    mac: str
    ipv4: List[str]
    attached_dpid: str
    attached_port: int


class TopologyGraph:
    """Adjacency-list network topology graph for SDN path analysis."""

    def __init__(self) -> None:
        """Initialize an empty topology graph."""
        # Adjacency list: node -> set of neighbor nodes
        self.adj: Dict[str, Set[str]] = {}
        # Switches tracked: dpid -> set of port numbers
        self.switches: Dict[str, Set[int]] = {}
        # Links: (u, v) -> (port_u, port_v)
        self.link_ports: Dict[Tuple[str, str], Tuple[int, int]] = {}
        # Hosts: host_id -> HostNode
        self.hosts: Dict[str, HostNode] = {}
        # IP to host_id lookup
        self.ip_to_host: Dict[str, str] = {}

    def _normalize_dpid(self, dpid: Any) -> str:
        """Normalize DPID to a clean hex string representation."""
        if isinstance(dpid, int):
            return f"{dpid:016x}"
        s = str(dpid).strip().lower()
        if s.startswith("0x"):
            s = s[2:]
        if len(s) < 16 and all(c in "0123456789abcdef" for c in s):
            return s.zfill(16)
        return s

    def add_switch(self, dpid: Any) -> str:
        """Add a switch node to the graph.

        Args:
            dpid: Datapath ID (int or str)

        Returns:
            Normalized DPID string.
        """
        node_id = self._normalize_dpid(dpid)
        if node_id not in self.adj:
            self.adj[node_id] = set()
        if node_id not in self.switches:
            self.switches[node_id] = set()
        return node_id

    def add_link(
        self,
        src_dpid: Any,
        src_port: int,
        dst_dpid: Any,
        dst_port: int,
    ) -> None:
        """Add a bidirectional link between two switches.

        Args:
            src_dpid: Source datapath ID
            src_port: Port number on source switch
            dst_dpid: Destination datapath ID
            dst_port: Port number on destination switch
        """
        u = self.add_switch(src_dpid)
        v = self.add_switch(dst_dpid)

        self.switches[u].add(src_port)
        self.switches[v].add(dst_port)

        self.adj[u].add(v)
        self.adj[v].add(u)

        self.link_ports[(u, v)] = (src_port, dst_port)
        self.link_ports[(v, u)] = (dst_port, src_port)

    def add_host(
        self,
        host_id: str,
        mac: str,
        ipv4: str | List[str],
        attached_dpid: Any,
        attached_port: int,
    ) -> str:
        """Add an end host attached to a switch port.

        Args:
            host_id: Identifier or name for the host (e.g. 'h1')
            mac: Hardware MAC address
            ipv4: IPv4 address string or list of IPv4 strings
            attached_dpid: Switch datapath ID to which the host connects
            attached_port: Port number on switch where host connects

        Returns:
            Host identifier.
        """
        sw_id = self.add_switch(attached_dpid)
        self.switches[sw_id].add(attached_port)

        ip_list = [ipv4] if isinstance(ipv4, str) else list(ipv4)
        node = HostNode(
            host_id=host_id,
            mac=mac,
            ipv4=ip_list,
            attached_dpid=sw_id,
            attached_port=attached_port,
        )

        self.hosts[host_id] = node
        for ip in ip_list:
            if ip:
                self.ip_to_host[ip] = host_id

        if host_id not in self.adj:
            self.adj[host_id] = set()

        # Connect host and switch bidirectionally
        self.adj[host_id].add(sw_id)
        self.adj[sw_id].add(host_id)
        self.link_ports[(host_id, sw_id)] = (0, attached_port)
        self.link_ports[(sw_id, host_id)] = (attached_port, 0)

        return host_id

    def build_from_topology_data(self, data: Dict[str, Any]) -> None:
        """Populate graph from structured topology dictionary.

        Args:
            data: Dictionary with 'switches', 'links', and 'hosts' keys.
        """
        # 1. Add switches
        for sw in data.get("switches", []):
            dpid = sw.get("dpid") or sw.get("dpid_int")
            if dpid is not None:
                sw_id = self.add_switch(dpid)
                for port in sw.get("ports", []):
                    port_no = port.get("port_no")
                    if isinstance(port_no, int):
                        self.switches[sw_id].add(port_no)

        # 2. Add links
        for link in data.get("links", []):
            src_dpid = link.get("src_dpid")
            src_port = link.get("src_port")
            dst_dpid = link.get("dst_dpid")
            dst_port = link.get("dst_port")
            if src_dpid is not None and dst_dpid is not None:
                self.add_link(
                    src_dpid,
                    int(src_port or 0),
                    dst_dpid,
                    int(dst_port or 0),
                )

        # 3. Add hosts
        for host in data.get("hosts", []):
            mac = host.get("mac", "")
            ipv4 = host.get("ipv4", [])
            dpid = host.get("dpid")
            port = host.get("port", 0)
            host_id = host.get("host_id") or mac or f"host_{dpid}_{port}"
            if dpid:
                self.add_host(
                    host_id=host_id,
                    mac=mac,
                    ipv4=ipv4,
                    attached_dpid=dpid,
                    attached_port=int(port),
                )

    def find_all_paths(self, src: str, dst: str) -> List[PathResult]:
        """Find all simple paths between two nodes using DFS.

        Args:
            src: Source node identifier (switch DPID or host ID)
            dst: Destination node identifier (switch DPID or host ID)

        Returns:
            List of PathResult objects sorted by path length (hops).
        """
        src = self._resolve_node_identifier(src)
        dst = self._resolve_node_identifier(dst)

        if not src or not dst or src not in self.adj or dst not in self.adj:
            return []

        if src == dst:
            return [PathResult(path=[src], length=0, is_shortest=True)]

        all_paths: List[List[str]] = []
        visited: Set[str] = set()

        def dfs(current: str, target: str, current_path: List[str]) -> None:
            if current == target:
                all_paths.append(list(current_path))
                return

            visited.add(current)
            for neighbor in sorted(self.adj.get(current, [])):
                if neighbor not in visited:
                    current_path.append(neighbor)
                    dfs(neighbor, target, current_path)
                    current_path.pop()
            visited.remove(current)

        dfs(src, dst, [src])

        if not all_paths:
            return []

        # Calculate lengths and find shortest
        min_len = min(len(p) - 1 for p in all_paths)
        results: List[PathResult] = []
        for p in all_paths:
            hop_count = len(p) - 1
            results.append(
                PathResult(
                    path=p,
                    length=hop_count,
                    is_shortest=(hop_count == min_len),
                )
            )

        results.sort(key=lambda pr: (pr.length, pr.path))
        return results

    def find_shortest_path(self, src: str, dst: str) -> Optional[PathResult]:
        """Find the shortest path between two nodes using BFS.

        Args:
            src: Source node identifier
            dst: Destination node identifier

        Returns:
            PathResult with the shortest path, or None if no path exists.
        """
        src = self._resolve_node_identifier(src)
        dst = self._resolve_node_identifier(dst)

        if not src or not dst or src not in self.adj or dst not in self.adj:
            return None

        if src == dst:
            return PathResult(path=[src], length=0, is_shortest=True)

        queue: deque[List[str]] = deque([[src]])
        visited: Set[str] = {src}

        while queue:
            current_path = queue.popleft()
            node = current_path[-1]

            for neighbor in sorted(self.adj.get(node, [])):
                if neighbor == dst:
                    final_path = current_path + [neighbor]
                    return PathResult(
                        path=final_path,
                        length=len(final_path) - 1,
                        is_shortest=True,
                    )
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(current_path + [neighbor])

        return None

    def get_paths_between_hosts(self, host1_ip: str, host2_ip: str) -> List[PathResult]:
        """Find candidate paths between two hosts identified by IP address.

        Args:
            host1_ip: IPv4 address of source host
            host2_ip: IPv4 address of destination host

        Returns:
            List of candidate PathResults between the hosts.
        """
        h1 = self.ip_to_host.get(host1_ip)
        h2 = self.ip_to_host.get(host2_ip)

        if not h1 or not h2:
            return []

        return self.find_all_paths(h1, h2)

    def _resolve_node_identifier(self, identifier: str) -> str:
        """Resolve IP, DPID, or host_id to graph node key."""
        # 1. Check IP mapping
        if identifier in self.ip_to_host:
            return self.ip_to_host[identifier]
        # 2. Check directly in adj
        if identifier in self.adj:
            return identifier
        # 3. Check normalized DPID
        norm = self._normalize_dpid(identifier)
        if norm in self.adj:
            return norm
        return identifier


def main() -> None:
    """Demonstrate graph-based path analysis on a diamond topology."""
    print("=== Topology Graph & Path Analysis Test ===")
    graph = TopologyGraph()

    # Create Diamond topology:
    #   h1 (10.0.0.1) --- s1 --- s2 --- s4 --- h2 (10.0.0.2)
    #                      \            /
    #                       --- s3 ----
    s1 = "0000000000000001"
    s2 = "0000000000000002"
    s3 = "0000000000000003"
    s4 = "0000000000000004"

    graph.add_link(s1, 1, s2, 1)
    graph.add_link(s1, 2, s3, 1)
    graph.add_link(s2, 2, s4, 1)
    graph.add_link(s3, 2, s4, 2)

    graph.add_host("h1", "00:00:00:00:00:01", "10.0.0.1", s1, 3)
    graph.add_host("h2", "00:00:00:00:00:02", "10.0.0.2", s4, 3)

    print(f"Graph nodes: {list(graph.adj.keys())}")
    paths = graph.get_paths_between_hosts("10.0.0.1", "10.0.0.2")

    print(f"\nPaths between 10.0.0.1 and 10.0.0.2: {len(paths)} found")
    for i, p in enumerate(paths, 1):
        path_str = " -> ".join(p.path)
        star = " (Shortest)" if p.is_shortest else ""
        print(f"  Path {i} [hops={p.length}]: {path_str}{star}")

    shortest = graph.find_shortest_path("h1", "h2")
    if shortest:
        print(f"\nShortest Path: {' -> '.join(shortest.path)} ({shortest.length} hops)")


if __name__ == "__main__":
    main()
