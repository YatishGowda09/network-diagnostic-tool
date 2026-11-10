"""Ryu SDN Controller with L2 Learning Switch and REST Topology Discovery.

Implements an OpenFlow 1.3 controller with dynamic shortest-path rerouting,
LLDP topology discovery, stale flow eviction, and REST monitoring endpoints.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("RyuController")


class NetworkGraph:
    """In-memory switch-level adjacency graph for dynamic path computation."""

    def __init__(self) -> None:
        self.adj: Dict[int, Dict[int, Tuple[int, int]]] = {}
        self.switches: Dict[int, Set[int]] = {}
        self.hosts: Dict[str, Dict[str, Any]] = {}

    def _normalize_dpid(self, dpid: Any) -> int:
        """Normalize DPID from int or hex string to integer."""
        if isinstance(dpid, int):
            return dpid
        s = str(dpid).strip().lower()
        return int(s[2:] if s.startswith("0x") else s, 16)

    def add_switch(self, dpid: Any) -> int:
        """Add a switch to the graph if not already present."""
        d = self._normalize_dpid(dpid)
        self.adj.setdefault(d, {})
        self.switches.setdefault(d, set())
        return d

    def remove_switch(self, dpid: Any) -> None:
        """Remove a switch and all its connecting links and hosts."""
        d = self._normalize_dpid(dpid)
        self.adj.pop(d, None)
        self.switches.pop(d, None)
        for neighbors in self.adj.values():
            neighbors.pop(d, None)
        self.hosts = {mac: info for mac, info in self.hosts.items() if info.get("dpid") != d}

    def add_link(self, src_dpid: Any, src_port: int, dst_dpid: Any, dst_port: int) -> None:
        """Add or update a bidirectional link between two switches."""
        u, v = self.add_switch(src_dpid), self.add_switch(dst_dpid)
        self.switches[u].add(src_port)
        self.switches[v].add(dst_port)
        self.adj[u][v] = (src_port, dst_port)
        self.adj[v][u] = (dst_port, src_port)

    def remove_link(self, src_dpid: Any, dst_dpid: Any) -> bool:
        """Remove bidirectional link between two switches."""
        u, v = self._normalize_dpid(src_dpid), self._normalize_dpid(dst_dpid)
        r1 = self.adj.get(u, {}).pop(v, None) is not None
        r2 = self.adj.get(v, {}).pop(u, None) is not None
        return r1 or r2

    def add_host(self, mac: str, dpid: Any, port: int, ipv4: Optional[List[str] | str] = None) -> None:
        """Register or update an attached end host."""
        d = self.add_switch(dpid)
        self.switches[d].add(port)
        ip_list = [ipv4] if isinstance(ipv4, str) else list(ipv4 or [])
        self.hosts[mac] = {"dpid": d, "port": port, "ipv4": ip_list}

    def shortest_path(self, src_dpid: Any, dst_dpid: Any) -> List[int]:
        """Compute shortest path (minimum hop count) using BFS."""
        src, dst = self._normalize_dpid(src_dpid), self._normalize_dpid(dst_dpid)
        if src not in self.adj or dst not in self.adj:
            return []
        if src == dst:
            return [src]

        queue: deque[List[int]] = deque([[src]])
        visited: Set[int] = {src}

        while queue:
            path = queue.popleft()
            node = path[-1]
            for neighbor in sorted(self.adj.get(node, {}).keys()):
                if neighbor == dst:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def all_paths(self, src_dpid: Any, dst_dpid: Any) -> List[List[int]]:
        """Compute all simple, loop-free paths using DFS with backtracking."""
        src, dst = self._normalize_dpid(src_dpid), self._normalize_dpid(dst_dpid)
        if src not in self.adj or dst not in self.adj:
            return []
        if src == dst:
            return [[src]]

        paths: List[List[int]] = []
        visited: Set[int] = set()

        def dfs(curr: int, target: int, path: List[int]) -> None:
            if curr == target:
                paths.append(list(path))
                return
            visited.add(curr)
            for neighbor in sorted(self.adj.get(curr, {}).keys()):
                if neighbor not in visited:
                    path.append(neighbor)
                    dfs(neighbor, target, path)
                    path.pop()
            visited.remove(curr)

        dfs(src, dst, [src])
        paths.sort(key=lambda p: (len(p), p))
        return paths

    def get_out_port(self, curr_dpid: Any, next_dpid: Any) -> Optional[int]:
        """Get outgoing port on curr_dpid leading to next_dpid."""
        curr, nxt = self._normalize_dpid(curr_dpid), self._normalize_dpid(next_dpid)
        link = self.adj.get(curr, {}).get(nxt)
        return link[0] if link else None


# -----------------------------------------------------------------------------
# Ryu Integration & REST Controller
# -----------------------------------------------------------------------------
try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.ofproto import ofproto_v1_3
    from ryu.lib.packet import packet, ethernet, ether_types
    from ryu.app.wsgi import ControllerBase, WSGIApplication, route, Response
    from ryu.topology import event as topo_event
    from ryu.topology.api import get_switch, get_link, get_host

    RYU_AVAILABLE = True
except ImportError:
    try:
        from os_ken.base import app_manager  # type: ignore
        from os_ken.controller import ofp_event  # type: ignore
        from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls  # type: ignore
        from os_ken.ofproto import ofproto_v1_3  # type: ignore
        from os_ken.lib.packet import packet, ethernet, ether_types  # type: ignore
        from os_ken.app.wsgi import ControllerBase, WSGIApplication, route, Response  # type: ignore
        from os_ken.topology import event as topo_event  # type: ignore
        from os_ken.topology.api import get_switch, get_link, get_host  # type: ignore

        RYU_AVAILABLE = True
    except ImportError:
        RYU_AVAILABLE = False

if not RYU_AVAILABLE:
    class DummyBase:
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    app_manager = DummyBase()  # type: ignore
    app_manager.RyuApp = DummyBase  # type: ignore
    ControllerBase = DummyBase  # type: ignore
    def set_ev_cls(*args: Any, **kwargs: Any): return lambda f: f  # type: ignore
    def route(*args: Any, **kwargs: Any): return lambda f: f  # type: ignore


if RYU_AVAILABLE:
    class TopologyRestController(ControllerBase):
        """REST API controller exposing discovered network topology endpoints."""

        def __init__(self, req: Any, link: Any, data: Dict[str, Any], **config: Any) -> None:
            super().__init__(req, link, data, **config)
            self.app: NetworkController = data["app"]

        def _json_resp(self, data: Any) -> Response:
            return Response(content_type="application/json", body=json.dumps(data, indent=2).encode("utf-8"))

        @route("topology", "/topology/switches", methods=["GET"])
        def list_switches(self, req: Any, **kwargs: Any) -> Response:
            return self._json_resp(self.app.get_switches_data())

        @route("topology", "/topology/links", methods=["GET"])
        def list_links(self, req: Any, **kwargs: Any) -> Response:
            return self._json_resp(self.app.get_links_data())

        @route("topology", "/topology/hosts", methods=["GET"])
        def list_hosts(self, req: Any, **kwargs: Any) -> Response:
            return self._json_resp(self.app.get_hosts_data())

        @route("topology", "/topology/full", methods=["GET"])
        def get_full_topology(self, req: Any, **kwargs: Any) -> Response:
            return self._json_resp(self.app.get_full_topology_data())

        @route("topology", "/topology/status", methods=["GET"])
        def get_topology_status(self, req: Any, **kwargs: Any) -> Response:
            return self._json_resp(self.app.get_topology_status_data())


    class NetworkController(app_manager.RyuApp):
        """OpenFlow 1.3 L2 Learning Switch with LLDP discovery, dynamic rerouting, and REST API."""

        OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
        _CONTEXTS = {"wsgi": WSGIApplication}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.mac_to_port: Dict[int, Dict[str, int]] = {}
            self.datapaths: Dict[int, Any] = {}
            self.network_graph = NetworkGraph()
            self.topology_events: List[Dict[str, Any]] = []

            wsgi: WSGIApplication = kwargs["wsgi"]
            wsgi.register(TopologyRestController, {"app": self})
            self.logger.info("Topology REST API registered at /topology/*")

        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def switch_features_handler(self, ev: Any) -> None:
            """Install table-miss rule upon switch connection."""
            dp = ev.msg.datapath
            self.datapaths[dp.id] = dp
            self.network_graph.add_switch(dp.id)

            match = dp.ofproto_parser.OFPMatch()
            actions = [dp.ofproto_parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER, dp.ofproto.OFPCML_NO_BUFFER)]
            self.add_flow(dp, priority=0, match=match, actions=actions)
            self.logger.info("Switch connected: dpid=%016x", dp.id)

        def add_flow(
            self,
            datapath: Any,
            priority: int,
            match: Any,
            actions: List[Any],
            buffer_id: Optional[int] = None,
            idle_timeout: int = 0,
        ) -> None:
            """Install flow rule into switch flow table."""
            parser = datapath.ofproto_parser
            inst = [parser.OFPInstructionActions(datapath.ofproto.OFPIT_APPLY_ACTIONS, actions)]
            bid = buffer_id if (buffer_id is not None and buffer_id != datapath.ofproto.OFP_NO_BUFFER) else datapath.ofproto.OFP_NO_BUFFER
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=bid, priority=priority, match=match, instructions=inst, idle_timeout=idle_timeout)
            datapath.send_msg(mod)

        @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
        def packet_in_handler(self, ev: Any) -> None:
            """Handle incoming packets for L2 MAC learning and forwarding."""
            msg = ev.msg
            dp = msg.datapath
            in_port = msg.match["in_port"]
            pkt = packet.Packet(msg.data)
            eth = pkt.get_protocols(ethernet.ethernet)[0]

            if eth.ethertype == ether_types.ETH_TYPE_LLDP:
                return

            dst, src, dpid = eth.dst, eth.src, dp.id
            self.mac_to_port.setdefault(dpid, {})[src] = in_port

            out_port = self.mac_to_port[dpid].get(dst, dp.ofproto.OFPP_FLOOD)
            actions = [dp.ofproto_parser.OFPActionOutput(out_port)]

            if out_port != dp.ofproto.OFPP_FLOOD:
                match = dp.ofproto_parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
                self.add_flow(dp, priority=1, match=match, actions=actions, buffer_id=msg.buffer_id, idle_timeout=60)
                if msg.buffer_id != dp.ofproto.OFP_NO_BUFFER:
                    return

            data = msg.data if msg.buffer_id == dp.ofproto.OFP_NO_BUFFER else None
            out = dp.ofproto_parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data)
            dp.send_msg(out)

        def delete_flows_by_out_port(self, datapath: Any, out_port: int) -> None:
            """Purge all flow entries routing out of out_port (OFPFC_DELETE)."""
            if not datapath:
                return
            mod = datapath.ofproto_parser.OFPFlowMod(
                datapath=datapath,
                command=datapath.ofproto.OFPFC_DELETE,
                out_port=out_port,
                out_group=datapath.ofproto.OFPG_ANY,
                match=datapath.ofproto_parser.OFPMatch(),
            )
            datapath.send_msg(mod)
            self.logger.info("[SDN REROUTE] Purged stale flows on DPID=%016x out_port=%d", datapath.id, out_port)

        def _install_path_flows(self, path: List[int], src_mac: str, dst_mac: str, last_out_port: int) -> None:
            """Install proactive Priority 10 flow rules along computed path."""
            for idx, dpid in enumerate(path):
                dp = self.datapaths.get(dpid)
                if not dp:
                    continue
                out_port = last_out_port if idx == len(path) - 1 else self.network_graph.get_out_port(dpid, path[idx + 1])
                if out_port is not None:
                    match = dp.ofproto_parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                    self.add_flow(dp, priority=10, match=match, actions=[dp.ofproto_parser.OFPActionOutput(out_port)], idle_timeout=0)

        def recompute_and_install_paths(self) -> None:
            """Recompute shortest paths between all discovered hosts and install flows."""
            items = list(self.network_graph.hosts.items())
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    mac_a, info_a = items[i]
                    mac_b, info_b = items[j]
                    path_ab = self.network_graph.shortest_path(info_a["dpid"], info_b["dpid"])
                    if path_ab:
                        self._install_path_flows(path_ab, mac_a, mac_b, info_b["port"])
                        self._install_path_flows(list(reversed(path_ab)), mac_b, mac_a, info_a["port"])
                        self.logger.info("[SDN REROUTE] Active path installed: %s", " -> ".join(f"s{d}" for d in path_ab))

        @set_ev_cls(topo_event.EventSwitchEnter)
        def switch_enter_handler(self, ev: Any) -> None:
            sw = ev.switch
            self.datapaths[sw.dp.id] = sw.dp
            self.network_graph.add_switch(sw.dp.id)
            self.topology_events.append({"type": "switch_enter", "dpid": f"{sw.dp.id:016x}", "timestamp": time.time()})
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventSwitchLeave)
        def switch_leave_handler(self, ev: Any) -> None:
            dpid = ev.switch.dp.id
            self.datapaths.pop(dpid, None)
            self.mac_to_port.pop(dpid, None)
            self.network_graph.remove_switch(dpid)
            self.topology_events.append({"type": "switch_leave", "dpid": f"{dpid:016x}", "timestamp": time.time()})
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventLinkAdd)
        def link_add_handler(self, ev: Any) -> None:
            l = ev.link
            self.network_graph.add_link(l.src.dpid, l.src.port_no, l.dst.dpid, l.dst.port_no)
            self.topology_events.append({"type": "link_add", "src_dpid": f"{l.src.dpid:016x}", "dst_dpid": f"{l.dst.dpid:016x}", "timestamp": time.time()})
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventLinkDelete)
        def link_delete_handler(self, ev: Any) -> None:
            """Handle link failure: purge stale flows and dynamically reroute."""
            l = ev.link
            self.logger.warning("[TOPO] LINK FAILED: %016x:%d <---> %016x:%d", l.src.dpid, l.src.port_no, l.dst.dpid, l.dst.port_no)
            self.network_graph.remove_link(l.src.dpid, l.dst.dpid)
            self.topology_events.append({"type": "link_delete", "src_dpid": f"{l.src.dpid:016x}", "dst_dpid": f"{l.dst.dpid:016x}", "timestamp": time.time()})

            for dpid, port in [(l.src.dpid, l.src.port_no), (l.dst.dpid, l.dst.port_no)]:
                if dpid in self.datapaths:
                    self.delete_flows_by_out_port(self.datapaths[dpid], port)
                if dpid in self.mac_to_port:
                    self.mac_to_port[dpid] = {m: p for m, p in self.mac_to_port[dpid].items() if p != port}

            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventHostAdd)
        def host_add_handler(self, ev: Any) -> None:
            h = ev.host
            self.network_graph.add_host(mac=h.mac, dpid=h.port.dpid, port=h.port.port_no, ipv4=h.ipv4 or [])
            self.topology_events.append({"type": "host_add", "mac": h.mac, "dpid": f"{h.port.dpid:016x}", "timestamp": time.time()})
            self.recompute_and_install_paths()

        def get_topology_status_data(self) -> Dict[str, Any]:
            """Retrieve real-time SDN controller status, paths, and recent events."""
            items = list(self.network_graph.hosts.items())
            active_paths: Dict[str, Any] = {}
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    mac_a, info_a = items[i]
                    mac_b, info_b = items[j]
                    path = self.network_graph.shortest_path(info_a["dpid"], info_b["dpid"])
                    active_paths[f"{mac_a} <-> {mac_b}"] = {
                        "path": [f"{d:016x}" for d in path],
                        "hops": max(0, len(path) - 1),
                        "status": "active" if path else "disconnected",
                    }
            return {
                "switches_online": len(self.datapaths),
                "links_active": sum(len(v) for v in self.network_graph.adj.values()) // 2,
                "hosts_tracked": len(self.network_graph.hosts),
                "active_paths": active_paths,
                "recent_events": self.topology_events[-20:],
            }

        def get_switches_data(self) -> List[Dict[str, Any]]:
            try:
                switches = get_switch(self) or []
            except Exception:
                return []
            return [
                {
                    "dpid": f"{sw.dp.id:016x}",
                    "dpid_int": sw.dp.id,
                    "ports": [{"port_no": p.port_no, "name": p.name.decode() if isinstance(p.name, bytes) else str(p.name), "hw_addr": p.hw_addr} for p in getattr(sw, "ports", [])],
                }
                for sw in switches
            ]

        def get_links_data(self) -> List[Dict[str, Any]]:
            try:
                links = get_link(self) or []
            except Exception:
                return []
            return [{"src_dpid": f"{l.src.dpid:016x}", "src_port": l.src.port_no, "dst_dpid": f"{l.dst.dpid:016x}", "dst_port": l.dst.port_no} for l in links]

        def get_hosts_data(self) -> List[Dict[str, Any]]:
            try:
                hosts = get_host(self) or []
            except Exception:
                return []
            return [{"mac": h.mac, "ipv4": h.ipv4 or [], "dpid": f"{h.port.dpid:016x}", "port": h.port.port_no} for h in hosts]

        def get_full_topology_data(self) -> Dict[str, Any]:
            return {"switches": self.get_switches_data(), "links": self.get_links_data(), "hosts": self.get_hosts_data()}

else:
    class NetworkController:  # type: ignore
        pass


def main() -> None:
    print(f"Ryu Network Controller module. Ryu installed: {RYU_AVAILABLE}")


if __name__ == "__main__":
    main()
