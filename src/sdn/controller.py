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
from typing import Any, Dict, List, Optional

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


    class NetworkController(app_manager.RyuApp):
        """OpenFlow 1.3 L2 Learning Switch with LLDP topology discovery and REST API."""

        OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
        _CONTEXTS = {"wsgi": WSGIApplication}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # mac_to_port table: dpid -> {mac_address: in_port}
            self.mac_to_port: Dict[int, Dict[str, int]] = {}

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
        # Topology Event Listeners
        # ---------------------------------------------------------------------
        @set_ev_cls(topo_event.EventSwitchEnter)
        def switch_enter_handler(self, ev: Any) -> None:
            """Notify on switch addition."""
            switch = ev.switch
            self.logger.info(
                "[TOPO] Switch discovered: DPID=%016x (Ports: %d)",
                switch.dp.id,
                len(switch.ports),
            )

        @set_ev_cls(topo_event.EventSwitchLeave)
        def switch_leave_handler(self, ev: Any) -> None:
            """Notify on switch removal."""
            switch = ev.switch
            self.logger.warning("[TOPO] Switch removed: DPID=%016x", switch.dp.id)

        @set_ev_cls(topo_event.EventLinkAdd)
        def link_add_handler(self, ev: Any) -> None:
            """Notify on link addition."""
            link = ev.link
            self.logger.info(
                "[TOPO] Link detected: %016x:%d -> %016x:%d",
                link.src.dpid,
                link.src.port_no,
                link.dst.dpid,
                link.dst.port_no,
            )

        @set_ev_cls(topo_event.EventLinkDelete)
        def link_delete_handler(self, ev: Any) -> None:
            """Notify on link removal."""
            link = ev.link
            self.logger.warning(
                "[TOPO] Link removed: %016x:%d -> %016x:%d",
                link.src.dpid,
                link.src.port_no,
                link.dst.dpid,
                link.dst.port_no,
            )

        @set_ev_cls(topo_event.EventHostAdd)
        def host_add_handler(self, ev: Any) -> None:
            """Notify on host addition."""
            host = ev.host
            self.logger.info(
                "[TOPO] Host detected: MAC=%s, IP=%s, Attached=%016x:%d",
                host.mac,
                host.ipv4,
                host.port.dpid,
                host.port.port_no,
            )

        # ---------------------------------------------------------------------
        # Topology Data Fetchers
        # ---------------------------------------------------------------------
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
