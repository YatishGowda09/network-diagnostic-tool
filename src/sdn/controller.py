"""Ryu SDN Controller with L2 Learning Switch and REST Topology Discovery.

This module implements an OpenFlow 1.3 controller application using the Ryu SDN
Framework. It combines simple L2 MAC-learning forwarding with LLDP-based
network topology discovery and exposes topology information via a REST API.

Endpoints:
    - GET /topology/switches: List connected switches with port details
    - GET /topology/links: List active inter-switch links
    - GET /topology/hosts: List discovered end hosts
    - GET /topology/full: Aggregated topology view (switches, links, hosts)
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

# Module logger
logger = logging.getLogger("RyuController")


class NetworkGraph:
    """In-memory switch-level adjacency graph for dynamic SDN path computation.

    Maintains switch adjacency, port mappings, and host attachments to compute
    optimal forwarding paths and dynamically reroute traffic upon link failure.
    Usable both within Ryu controller and standalone for unit testing.
    """

    def __init__(self) -> None:
        """Initialize empty network graph."""
        # Adjacency: src_dpid -> {dst_dpid: (src_port, dst_port)}
        self.adj: Dict[int, Dict[int, Tuple[int, int]]] = {}
        # Switches tracked: dpid -> set of known active port numbers
        self.switches: Dict[int, Set[int]] = {}
        # Host tracking: mac_address -> {"dpid": int, "port": int, "ipv4": List[str]}
        self.hosts: Dict[str, Dict[str, Any]] = {}

    def _normalize_dpid(self, dpid: Any) -> int:
        """Normalize DPID from int or hex string to integer."""
        if isinstance(dpid, int):
            return dpid
        s = str(dpid).strip().lower()
        if s.startswith("0x"):
            s = s[2:]
        return int(s, 16)

    def add_switch(self, dpid: Any) -> int:
        """Add a switch to the graph if not already present."""
        d = self._normalize_dpid(dpid)
        if d not in self.adj:
            self.adj[d] = {}
        if d not in self.switches:
            self.switches[d] = set()
        return d

    def remove_switch(self, dpid: Any) -> None:
        """Remove a switch and all its connecting links from the graph."""
        d = self._normalize_dpid(dpid)
        self.adj.pop(d, None)
        self.switches.pop(d, None)
        # Remove incoming edges from neighbors
        for neighbors in self.adj.values():
            neighbors.pop(d, None)
        # Remove any attached hosts
        stale_hosts = [mac for mac, info in self.hosts.items() if info.get("dpid") == d]
        for mac in stale_hosts:
            self.hosts.pop(mac, None)

    def add_link(
        self,
        src_dpid: Any,
        src_port: int,
        dst_dpid: Any,
        dst_port: int,
    ) -> None:
        """Add or update a bidirectional link between two switches."""
        u = self.add_switch(src_dpid)
        v = self.add_switch(dst_dpid)
        self.switches[u].add(src_port)
        self.switches[v].add(dst_port)

        self.adj[u][v] = (src_port, dst_port)
        self.adj[v][u] = (dst_port, src_port)

    def remove_link(self, src_dpid: Any, dst_dpid: Any) -> bool:
        """Remove bidirectional link between two switches.

        Returns:
            True if the link existed and was removed, False otherwise.
        """
        u = self._normalize_dpid(src_dpid)
        v = self._normalize_dpid(dst_dpid)
        removed = False
        if u in self.adj and v in self.adj[u]:
            self.adj[u].pop(v, None)
            removed = True
        if v in self.adj and u in self.adj[v]:
            self.adj[v].pop(u, None)
            removed = True
        return removed

    def add_host(
        self,
        mac: str,
        dpid: Any,
        port: int,
        ipv4: Optional[List[str] | str] = None,
    ) -> None:
        """Register or update an attached end host."""
        d = self.add_switch(dpid)
        self.switches[d].add(port)
        ip_list = [ipv4] if isinstance(ipv4, str) else list(ipv4 or [])
        self.hosts[mac] = {
            "dpid": d,
            "port": port,
            "ipv4": ip_list,
        }

    def shortest_path(self, src_dpid: Any, dst_dpid: Any) -> List[int]:
        """Compute the shortest path (minimum hop count) between two switches using BFS.

        Returns:
            List of DPIDs in order from source to destination, or empty list if no path.
        """
        src = self._normalize_dpid(src_dpid)
        dst = self._normalize_dpid(dst_dpid)

        if src not in self.adj or dst not in self.adj:
            return []

        if src == dst:
            return [src]

        queue: deque[List[int]] = deque([[src]])
        visited: Set[int] = {src}

        while queue:
            current_path = queue.popleft()
            node = current_path[-1]

            # Sort neighbors for deterministic path selection
            for neighbor in sorted(self.adj.get(node, {}).keys()):
                if neighbor == dst:
                    return current_path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(current_path + [neighbor])

        return []

    def all_paths(self, src_dpid: Any, dst_dpid: Any) -> List[List[int]]:
        """Compute all simple, loop-free paths between two switches using DFS."""
        src = self._normalize_dpid(src_dpid)
        dst = self._normalize_dpid(dst_dpid)

        if src not in self.adj or dst not in self.adj:
            return []

        if src == dst:
            return [[src]]

        paths: List[List[int]] = []
        visited: Set[int] = set()

        def dfs(current: int, target: int, current_path: List[int]) -> None:
            if current == target:
                paths.append(list(current_path))
                return

            visited.add(current)
            for neighbor in sorted(self.adj.get(current, {}).keys()):
                if neighbor not in visited:
                    current_path.append(neighbor)
                    dfs(neighbor, target, current_path)
                    current_path.pop()
            visited.remove(current)

        dfs(src, dst, [src])
        paths.sort(key=lambda p: (len(p), p))
        return paths

    def get_out_port(self, curr_dpid: Any, next_dpid: Any) -> Optional[int]:
        """Get outgoing port on curr_dpid leading to next_dpid."""
        curr = self._normalize_dpid(curr_dpid)
        nxt = self._normalize_dpid(next_dpid)
        link = self.adj.get(curr, {}).get(nxt)
        return link[0] if link else None

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
    RYU_AVAILABLE = False
    # Define fallback dummy base classes when Ryu is not installed
    # so the file can be imported and parsed without throwing errors.
    class DummyBase:
        """Dummy placeholder when Ryu dependencies are unavailable."""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    app_manager = DummyBase()  # type: ignore
    app_manager.RyuApp = DummyBase  # type: ignore
    ControllerBase = DummyBase  # type: ignore

    def set_ev_cls(*args: Any, **kwargs: Any):  # type: ignore
        """Dummy decorator."""
        def decorator(func: Any) -> Any:
            return func
        return decorator

    def route(*args: Any, **kwargs: Any):  # type: ignore
        """Dummy decorator."""
        def decorator(func: Any) -> Any:
            return func
        return decorator


TOPOLOGY_API_NAME = "topology_api_app"


if RYU_AVAILABLE:
    class TopologyRestController(ControllerBase):
        """REST API controller exposing discovered network topology endpoints."""

        def __init__(self, req: Any, link: Any, data: Dict[str, Any], **config: Any) -> None:
            super().__init__(req, link, data, **config)
            self.app: NetworkController = data["app"]

        @route("topology", "/topology/switches", methods=["GET"])
        def list_switches(self, req: Any, **kwargs: Any) -> Response:
            """Return list of discovered switches with port details."""
            switches = self.app.get_switches_data()
            body = json.dumps(switches, indent=2)
            return Response(content_type="application/json", body=body.encode("utf-8"))

        @route("topology", "/topology/links", methods=["GET"])
        def list_links(self, req: Any, **kwargs: Any) -> Response:
            """Return list of discovered inter-switch links."""
            links = self.app.get_links_data()
            body = json.dumps(links, indent=2)
            return Response(content_type="application/json", body=body.encode("utf-8"))

        @route("topology", "/topology/hosts", methods=["GET"])
        def list_hosts(self, req: Any, **kwargs: Any) -> Response:
            """Return list of discovered hosts."""
            hosts = self.app.get_hosts_data()
            body = json.dumps(hosts, indent=2)
            return Response(content_type="application/json", body=body.encode("utf-8"))

        @route("topology", "/topology/full", methods=["GET"])
        def get_full_topology(self, req: Any, **kwargs: Any) -> Response:
            """Return full aggregated network topology."""
            topology = self.app.get_full_topology_data()
            body = json.dumps(topology, indent=2)
            return Response(content_type="application/json", body=body.encode("utf-8"))

        @route("topology", "/topology/status", methods=["GET"])
        def get_topology_status(self, req: Any, **kwargs: Any) -> Response:
            """Return dynamic SDN operational status, active paths, and event history."""
            status = self.app.get_topology_status_data()
            body = json.dumps(status, indent=2)
            return Response(content_type="application/json", body=body.encode("utf-8"))


    class NetworkController(app_manager.RyuApp):
        """OpenFlow 1.3 L2 Learning Switch with LLDP topology discovery and REST API."""

        OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
        _CONTEXTS = {"wsgi": WSGIApplication}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # mac_to_port table: dpid -> {mac_address: in_port}
            self.mac_to_port: Dict[int, Dict[str, int]] = {}

            # Active OpenFlow datapath objects indexed by integer DPID
            self.datapaths: Dict[int, Any] = {}

            # In-memory switch adjacency graph for dynamic path finding & rerouting
            self.network_graph: NetworkGraph = NetworkGraph()

            # Audit history of topology changes and reroute events
            self.topology_events: List[Dict[str, Any]] = []

            # Register REST WSGI controller
            wsgi: WSGIApplication = kwargs["wsgi"]
            wsgi.register(TopologyRestController, {"app": self})
            self.logger.info("Topology REST API registered at /topology/*")

        # ---------------------------------------------------------------------
        # Switch Configuration & OpenFlow Handlers
        # ---------------------------------------------------------------------
        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def switch_features_handler(self, ev: Any) -> None:
            """Install table-miss flow entry upon switch connection."""
            datapath = ev.msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            # Track datapath object for proactive flow manipulation
            self.datapaths[datapath.id] = datapath
            self.network_graph.add_switch(datapath.id)

            # Install table-miss flow entry: send all unmatched packets to controller
            match = parser.OFPMatch()
            actions = [
                parser.OFPActionOutput(
                    ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER
                )
            ]
            self.add_flow(datapath, priority=0, match=match, actions=actions)
            self.logger.info("Switch connected: dpid=%016x", datapath.id)

        def add_flow(
            self,
            datapath: Any,
            priority: int,
            match: Any,
            actions: List[Any],
            buffer_id: Optional[int] = None,
            idle_timeout: int = 0,
        ) -> None:
            """Install flow rule into switch table."""
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS, actions
                )
            ]

            if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    buffer_id=buffer_id,
                    priority=priority,
                    match=match,
                    instructions=instructions,
                    idle_timeout=idle_timeout,
                )
            else:
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=priority,
                    match=match,
                    instructions=instructions,
                    idle_timeout=idle_timeout,
                )
            datapath.send_msg(mod)

        @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
        def packet_in_handler(self, ev: Any) -> None:
            """Handle incoming packets for L2 learning and forwarding."""
            msg = ev.msg
            datapath = msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            in_port = msg.match["in_port"]

            pkt = packet.Packet(msg.data)
            eth = pkt.get_protocols(ethernet.ethernet)[0]

            # Ignore LLDP packet-in (handled by Ryu topology discovery)
            if eth.ethertype == ether_types.ETH_TYPE_LLDP:
                return

            dst = eth.dst
            src = eth.src
            dpid = datapath.id

            self.mac_to_port.setdefault(dpid, {})

            # Learn source MAC address to avoid flooding next time
            self.mac_to_port[dpid][src] = in_port

            # Check if destination port is known
            if dst in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst]
            else:
                out_port = ofproto.OFPP_FLOOD

            actions = [parser.OFPActionOutput(out_port)]

            # Install flow rule if destination is known (idle_timeout=60 seconds)
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
                if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                    self.add_flow(
                        datapath,
                        priority=1,
                        match=match,
                        actions=actions,
                        buffer_id=msg.buffer_id,
                        idle_timeout=60,
                    )
                    return
                else:
                    self.add_flow(
                        datapath,
                        priority=1,
                        match=match,
                        actions=actions,
                        idle_timeout=60,
                    )

            # Send packet out
            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data

            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data,
            )
            datapath.send_msg(out)

        # ---------------------------------------------------------------------
        # Dynamic SDN Forwarding & Path Installation
        # ---------------------------------------------------------------------
        def delete_flows_by_out_port(self, datapath: Any, out_port: int) -> None:
            """Remove all flow entries from switch that forward out of out_port."""
            if datapath is None:
                return
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = parser.OFPMatch()
            mod = parser.OFPFlowMod(
                datapath=datapath,
                command=ofproto.OFPFC_DELETE,
                out_port=out_port,
                out_group=ofproto.OFPG_ANY,
                match=match,
            )
            datapath.send_msg(mod)
            self.logger.info(
                "[SDN REROUTE] Purged stale flows on DPID=%016x out_port=%d",
                datapath.id,
                out_port,
            )

        def _install_path_flows(
            self,
            path: List[int],
            src_mac: str,
            dst_mac: str,
            last_out_port: int,
        ) -> None:
            """Install proactive flow entries along a computed switch path."""
            for idx, dpid in enumerate(path):
                datapath = self.datapaths.get(dpid)
                if not datapath:
                    continue
                parser = datapath.ofproto_parser

                if idx < len(path) - 1:
                    next_dpid = path[idx + 1]
                    out_port = self.network_graph.get_out_port(dpid, next_dpid)
                    if out_port is None:
                        continue
                else:
                    out_port = last_out_port

                match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                actions = [parser.OFPActionOutput(out_port)]
                # Priority 10 takes precedence over standard L2 learning rules (priority 1)
                self.add_flow(datapath, priority=10, match=match, actions=actions, idle_timeout=0)

        def recompute_and_install_paths(self) -> None:
            """Recompute shortest paths between all discovered hosts and install flows."""
            host_items = list(self.network_graph.hosts.items())
            if len(host_items) < 2:
                return

            for i in range(len(host_items)):
                for j in range(i + 1, len(host_items)):
                    mac_a, info_a = host_items[i]
                    mac_b, info_b = host_items[j]

                    dpid_a, port_a = info_a["dpid"], info_a["port"]
                    dpid_b, port_b = info_b["dpid"], info_b["port"]

                    path_ab = self.network_graph.shortest_path(dpid_a, dpid_b)
                    if path_ab:
                        # Forward direction A -> B
                        self._install_path_flows(path_ab, mac_a, mac_b, port_b)
                        # Reverse direction B -> A
                        path_ba = list(reversed(path_ab))
                        self._install_path_flows(path_ba, mac_b, mac_a, port_a)

                        path_str = " -> ".join(f"s{d}" for d in path_ab)
                        self.logger.info(
                            "[SDN REROUTE] Active path installed (%s -> %s): %s",
                            mac_a,
                            mac_b,
                            path_str,
                        )

        # ---------------------------------------------------------------------
        # Topology Event Listeners
        # ---------------------------------------------------------------------
        @set_ev_cls(topo_event.EventSwitchEnter)
        def switch_enter_handler(self, ev: Any) -> None:
            """Notify on switch addition and register datapath."""
            switch = ev.switch
            dpid = switch.dp.id
            self.datapaths[dpid] = switch.dp
            self.network_graph.add_switch(dpid)
            self.topology_events.append({
                "type": "switch_enter",
                "dpid": f"{dpid:016x}",
                "timestamp": time.time(),
            })
            self.logger.info(
                "[TOPO] Switch discovered: DPID=%016x (Ports: %d)",
                dpid,
                len(switch.ports),
            )
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventSwitchLeave)
        def switch_leave_handler(self, ev: Any) -> None:
            """Notify on switch removal and clear associations."""
            switch = ev.switch
            dpid = switch.dp.id
            self.datapaths.pop(dpid, None)
            self.mac_to_port.pop(dpid, None)
            self.network_graph.remove_switch(dpid)
            self.topology_events.append({
                "type": "switch_leave",
                "dpid": f"{dpid:016x}",
                "timestamp": time.time(),
            })
            self.logger.warning("[TOPO] Switch removed: DPID=%016x", dpid)
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventLinkAdd)
        def link_add_handler(self, ev: Any) -> None:
            """Notify on link addition, update graph, and recalculate paths."""
            link = ev.link
            src_dpid = link.src.dpid
            src_port = link.src.port_no
            dst_dpid = link.dst.dpid
            dst_port = link.dst.port_no

            self.network_graph.add_link(src_dpid, src_port, dst_dpid, dst_port)
            self.topology_events.append({
                "type": "link_add",
                "src_dpid": f"{src_dpid:016x}",
                "src_port": src_port,
                "dst_dpid": f"{dst_dpid:016x}",
                "dst_port": dst_port,
                "timestamp": time.time(),
            })
            self.logger.info(
                "[TOPO] Link detected: %016x:%d <---> %016x:%d",
                src_dpid,
                src_port,
                dst_dpid,
                dst_port,
            )
            self.recompute_and_install_paths()

        @set_ev_cls(topo_event.EventLinkDelete)
        def link_delete_handler(self, ev: Any) -> None:
            """Handle link failure: remove link, purge stale flows, and dynamically reroute."""
            link = ev.link
            src_dpid = link.src.dpid
            src_port = link.src.port_no
            dst_dpid = link.dst.dpid
            dst_port = link.dst.port_no

            self.logger.warning(
                "[TOPO] LINK FAILED: %016x:%d <---> %016x:%d — TRIGGERING DYNAMIC REROUTE",
                src_dpid,
                src_port,
                dst_dpid,
                dst_port,
            )

            # 1. Update graph by removing failed edge
            self.network_graph.remove_link(src_dpid, dst_dpid)

            # 2. Record failure event for monitoring
            self.topology_events.append({
                "type": "link_delete",
                "src_dpid": f"{src_dpid:016x}",
                "src_port": src_port,
                "dst_dpid": f"{dst_dpid:016x}",
                "dst_port": dst_port,
                "timestamp": time.time(),
            })

            # 3. Purge stale flow rules on switches connected to the failed link
            if src_dpid in self.datapaths:
                self.delete_flows_by_out_port(self.datapaths[src_dpid], src_port)
            if dst_dpid in self.datapaths:
                self.delete_flows_by_out_port(self.datapaths[dst_dpid], dst_port)

            # 4. Purge stale MAC-to-port cache entries pointing to the failed ports
            if src_dpid in self.mac_to_port:
                stale_macs_src = [mac for mac, port in self.mac_to_port[src_dpid].items() if port == src_port]
                for mac in stale_macs_src:
                    self.mac_to_port[src_dpid].pop(mac, None)

            if dst_dpid in self.mac_to_port:
                stale_macs_dst = [mac for mac, port in self.mac_to_port[dst_dpid].items() if port == dst_port]
                for mac in stale_macs_dst:
                    self.mac_to_port[dst_dpid].pop(mac, None)

            # 5. Proactively calculate and install alternative forwarding paths
            self.recompute_and_install_paths()
            self.logger.info("[TOPO] Dynamic rerouting and recovery complete.")

        @set_ev_cls(topo_event.EventHostAdd)
        def host_add_handler(self, ev: Any) -> None:
            """Register host location and install initial proactive routes."""
            host = ev.host
            mac = host.mac
            dpid = host.port.dpid
            port = host.port.port_no
            ipv4 = host.ipv4 if host.ipv4 else []

            self.network_graph.add_host(mac=mac, dpid=dpid, port=port, ipv4=ipv4)
            self.topology_events.append({
                "type": "host_add",
                "mac": mac,
                "dpid": f"{dpid:016x}",
                "port": port,
                "timestamp": time.time(),
            })
            self.logger.info(
                "[TOPO] Host detected: MAC=%s, IP=%s, Attached=%016x:%d",
                mac,
                ipv4,
                dpid,
                port,
            )
            self.recompute_and_install_paths()

        # ---------------------------------------------------------------------
        # Topology Data Fetchers & Monitoring
        # ---------------------------------------------------------------------
        def get_topology_status_data(self) -> Dict[str, Any]:
            """Retrieve real-time SDN controller status, paths, and recent events."""
            host_items = list(self.network_graph.hosts.items())
            active_paths: Dict[str, Any] = {}

            for i in range(len(host_items)):
                for j in range(i + 1, len(host_items)):
                    mac_a, info_a = host_items[i]
                    mac_b, info_b = host_items[j]
                    path = self.network_graph.shortest_path(info_a["dpid"], info_b["dpid"])
                    key = f"{mac_a} <-> {mac_b}"
                    active_paths[key] = {
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
            """Retrieve structured switch data from Ryu topology API."""
            try:
                switches = get_switch(self) or []
            except Exception as e:
                self.logger.error("Failed to query switch topology: %s", e)
                return []

            result = []
            for sw in switches:
                ports = [
                    {
                        "port_no": port.port_no,
                        "name": port.name.decode("utf-8") if isinstance(port.name, bytes) else str(port.name),
                        "hw_addr": port.hw_addr,
                    }
                    for port in getattr(sw, "ports", [])
                ]
                result.append(
                    {
                        "dpid": f"{sw.dp.id:016x}",
                        "dpid_int": sw.dp.id,
                        "ports": ports,
                    }
                )
            return result

        def get_links_data(self) -> List[Dict[str, Any]]:
            """Retrieve structured link data from Ryu topology API."""
            try:
                links = get_link(self) or []
            except Exception as e:
                self.logger.error("Failed to query link topology: %s", e)
                return []

            result = []
            for link in links:
                result.append(
                    {
                        "src_dpid": f"{link.src.dpid:016x}",
                        "src_port": link.src.port_no,
                        "dst_dpid": f"{link.dst.dpid:016x}",
                        "dst_port": link.dst.port_no,
                    }
                )
            return result

        def get_hosts_data(self) -> List[Dict[str, Any]]:
            """Retrieve structured host data from Ryu topology API."""
            try:
                hosts = get_host(self) or []
            except Exception as e:
                self.logger.error("Failed to query host topology: %s", e)
                return []

            result = []
            for host in hosts:
                result.append(
                    {
                        "mac": host.mac,
                        "ipv4": host.ipv4 if host.ipv4 else [],
                        "dpid": f"{host.port.dpid:016x}",
                        "port": host.port.port_no,
                    }
                )
            return result

        def get_full_topology_data(self) -> Dict[str, Any]:
            """Retrieve aggregate topology snapshot."""
            return {
                "switches": self.get_switches_data(),
                "links": self.get_links_data(),
                "hosts": self.get_hosts_data(),
            }

else:
    class NetworkController:  # type: ignore
        """Dummy NetworkController when Ryu is not installed."""
        pass


def main() -> None:
    """Print controller information when executed directly."""
    print("Ryu Network Controller module.")
    print(f"Ryu installed: {RYU_AVAILABLE}")
    print("To run with Ryu: ryu-manager --observe-links src/sdn/controller.py")


if __name__ == "__main__":
    main()
