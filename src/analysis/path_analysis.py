"""Graph-based network path analysis module.

Builds an in-memory graph representation of SDN/Mininet network topologies
and computes candidate forwarding paths and shortest paths using BFS and DFS.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class PathResult:
    """Represents a discovered candidate path between two network nodes."""

    path: List[str]
    length: int
    is_shortest: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "length": self.length, "is_shortest": self.is_shortest}


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
        self.adj: Dict[str, Set[str]] = {}
        self.switches: Dict[str, Set[int]] = {}
        self.link_ports: Dict[Tuple[str, str], Tuple[int, int]] = {}
        self.hosts: Dict[str, HostNode] = {}
        self.ip_to_host: Dict[str, str] = {}

    def _normalize_dpid(self, dpid: Any) -> str:
        """Normalize DPID to a clean 16-character hex string."""
        if isinstance(dpid, int):
            return f"{dpid:016x}"
        s = str(dpid).strip().lower()
        if s.startswith("0x"):
            s = s[2:]
        if len(s) < 16 and all(c in "0123456789abcdef" for c in s):
            return s.zfill(16)
        return s

    def add_switch(self, dpid: Any) -> str:
        """Add a switch node to the graph."""
        node_id = self._normalize_dpid(dpid)
        self.adj.setdefault(node_id, set())
        self.switches.setdefault(node_id, set())
        return node_id

    def add_link(self, src_dpid: Any, src_port: int, dst_dpid: Any, dst_port: int) -> None:
        """Add a bidirectional link between two switches."""
        u, v = self.add_switch(src_dpid), self.add_switch(dst_dpid)
        self.switches[u].add(src_port)
        self.switches[v].add(dst_port)
        self.adj[u].add(v)
        self.adj[v].add(u)
        self.link_ports[(u, v)] = (src_port, dst_port)
        self.link_ports[(v, u)] = (dst_port, src_port)

    def add_host(self, host_id: str, mac: str, ipv4: str | List[str], attached_dpid: Any, attached_port: int) -> str:
        """Add an end host attached to a switch port."""
        sw_id = self.add_switch(attached_dpid)
        self.switches[sw_id].add(attached_port)
        ip_list = [ipv4] if isinstance(ipv4, str) else list(ipv4)

        self.hosts[host_id] = HostNode(host_id, mac, ip_list, sw_id, attached_port)
        for ip in ip_list:
            if ip:
                self.ip_to_host[ip] = host_id

        self.adj.setdefault(host_id, set()).add(sw_id)
        self.adj[sw_id].add(host_id)
        self.link_ports[(host_id, sw_id)] = (0, attached_port)
        self.link_ports[(sw_id, host_id)] = (attached_port, 0)
        return host_id

    def build_from_topology_data(self, data: Dict[str, Any]) -> None:
        """Populate graph from structured controller JSON topology dict."""
        for sw in data.get("switches", []):
            dpid = sw.get("dpid") or sw.get("dpid_int")
            if dpid is not None:
                sw_id = self.add_switch(dpid)
                for port in sw.get("ports", []):
                    if isinstance(port.get("port_no"), int):
                        self.switches[sw_id].add(port["port_no"])

        for link in data.get("links", []):
            src, dst = link.get("src_dpid"), link.get("dst_dpid")
            if src is not None and dst is not None:
                self.add_link(src, int(link.get("src_port", 0) or 0), dst, int(link.get("dst_port", 0) or 0))

        for host in data.get("hosts", []):
            dpid = host.get("dpid")
            if dpid:
                hid = host.get("host_id") or host.get("mac") or f"host_{dpid}_{host.get('port', 0)}"
                self.add_host(hid, host.get("mac", ""), host.get("ipv4", []), dpid, int(host.get("port", 0)))

    def _resolve_node_identifier(self, identifier: str) -> str:
        """Resolve IP, DPID, or host_id to matching graph node key."""
        if identifier in self.ip_to_host:
            return self.ip_to_host[identifier]
        if identifier in self.adj:
            return identifier
        norm = self._normalize_dpid(identifier)
        return norm if norm in self.adj else identifier

    def find_all_paths(self, src: str, dst: str) -> List[PathResult]:
        """Find all simple loop-free paths using DFS with backtracking."""
        s, d = self._resolve_node_identifier(src), self._resolve_node_identifier(dst)
        if not s or not d or s not in self.adj or d not in self.adj:
            return []
        if s == d:
            return [PathResult(path=[s], length=0, is_shortest=True)]

        paths: List[List[str]] = []
        visited: Set[str] = set()

        def dfs(curr: str, target: str, path: List[str]) -> None:
            if curr == target:
                paths.append(list(path))
                return
            visited.add(curr)
            for neighbor in sorted(self.adj.get(curr, [])):
                if neighbor not in visited:
                    path.append(neighbor)
                    dfs(neighbor, target, path)
                    path.pop()
            visited.remove(curr)

        dfs(s, d, [s])
        if not paths:
            return []

        min_len = min(len(p) - 1 for p in paths)
        results = [PathResult(p, len(p) - 1, len(p) - 1 == min_len) for p in paths]
        results.sort(key=lambda pr: (pr.length, pr.path))
        return results

    def find_shortest_path(self, src: str, dst: str) -> Optional[PathResult]:
        """Find shortest path between two nodes using BFS."""
        s, d = self._resolve_node_identifier(src), self._resolve_node_identifier(dst)
        if not s or not d or s not in self.adj or d not in self.adj:
            return None
        if s == d:
            return PathResult(path=[s], length=0, is_shortest=True)

        queue: deque[List[str]] = deque([[s]])
        visited: Set[str] = {s}

        while queue:
            curr_path = queue.popleft()
            node = curr_path[-1]
            for neighbor in sorted(self.adj.get(node, [])):
                if neighbor == d:
                    final = curr_path + [neighbor]
                    return PathResult(path=final, length=len(final) - 1, is_shortest=True)
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(curr_path + [neighbor])
        return None

    def get_paths_between_hosts(self, host1_ip: str, host2_ip: str) -> List[PathResult]:
        """Find candidate paths between two hosts identified by IPv4."""
        h1, h2 = self.ip_to_host.get(host1_ip), self.ip_to_host.get(host2_ip)
        return self.find_all_paths(h1, h2) if h1 and h2 else []


def main() -> None:
    """Demonstrate graph-based path analysis on a diamond topology."""
    graph = TopologyGraph()
    s1, s2, s3, s4 = "0000000000000001", "0000000000000002", "0000000000000003", "0000000000000004"
    graph.add_link(s1, 1, s2, 1)
    graph.add_link(s1, 2, s3, 1)
    graph.add_link(s2, 2, s4, 1)
    graph.add_link(s3, 2, s4, 2)
    graph.add_host("h1", "00:00:00:00:00:01", "10.0.0.1", s1, 3)
    graph.add_host("h2", "00:00:00:00:00:02", "10.0.0.2", s4, 3)

    print(f"Graph nodes: {list(graph.adj.keys())}")
    for i, p in enumerate(graph.get_paths_between_hosts("10.0.0.1", "10.0.0.2"), 1):
        star = " (Shortest)" if p.is_shortest else ""
        print(f"  Path {i} [hops={p.length}]: {' -> '.join(p.path)}{star}")


if __name__ == "__main__":
    main()
