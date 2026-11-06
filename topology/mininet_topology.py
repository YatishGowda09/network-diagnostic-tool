"""Mininet Diamond (Rhombus) Topology for SDN Testing.

Creates a 4-switch diamond topology with 2 end hosts in Mininet:
                 +-------+
             +-->|  s2   |---+
             |   +-------+   |
  +----+   +-+-+           +-v-+   +----+
  | h1 |---> s1 |           | s4 |--> h2 |
  +----+   +-+-+           +-^-+   +----+
             |   +-------+   |
             +-->|  s3   |---+
                 +-------+
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:
    from mininet.cli import CLI
    from mininet.link import TCLink
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo

    MININET_AVAILABLE = True
except ImportError:
    MININET_AVAILABLE = False

    class Topo:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass


if MININET_AVAILABLE:
    class DiamondTopo(Topo):
        """Diamond topology with 4 OpenFlow 1.3 switches and 2 hosts."""

        def build(self, bw: int = 10, **kwargs: Any) -> None:
            s1 = self.addSwitch("s1", protocols="OpenFlow13")
            s2 = self.addSwitch("s2", protocols="OpenFlow13")
            s3 = self.addSwitch("s3", protocols="OpenFlow13")
            s4 = self.addSwitch("s4", protocols="OpenFlow13")

            h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
            h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

            self.addLink(h1, s1, bw=bw)
            self.addLink(h2, s4, bw=bw)
            self.addLink(s1, s2, bw=bw)
            self.addLink(s1, s3, bw=bw)
            self.addLink(s2, s4, bw=bw)
            self.addLink(s3, s4, bw=bw)


def inject_link_failure(net: Any, node1: str, node2: str) -> bool:
    """Programmatically bring down link between two nodes in Mininet."""
    try:
        net.configLinkStatus(node1, node2, "down")
        print(f"[FAULT INJECTION] Link {node1} <---> {node2} set to DOWN")
        return True
    except Exception as err:
        print(f"[ERROR] Failed to set link {node1}-{node2} down: {err}", file=sys.stderr)
        return False


def restore_link(net: Any, node1: str, node2: str) -> bool:
    """Programmatically restore link between two nodes in Mininet."""
    try:
        net.configLinkStatus(node1, node2, "up")
        print(f"[FAULT RECOVERY] Link {node1} <---> {node2} restored to UP")
        return True
    except Exception as err:
        print(f"[ERROR] Failed to restore link {node1}-{node2}: {err}", file=sys.stderr)
        return False


def run_diamond_network(controller_ip: str = "127.0.0.1", controller_port: int = 6633, bandwidth: int = 10) -> None:
    """Instantiate and start Mininet network with diamond topology."""
    if not MININET_AVAILABLE:
        print("ERROR: Mininet is not installed in this Python environment.", file=sys.stderr)
        sys.exit(1)
    if os.geteuid() != 0:
        print(f"ERROR: Mininet requires root privileges: sudo python3 {sys.argv[0]}", file=sys.stderr)
        sys.exit(1)

    setLogLevel("info")
    print(f"\n=== Mininet Diamond Topology (Controller: {controller_ip}:{controller_port}, BW: {bandwidth} Mbps) ===")

    topo = DiamondTopo(bw=bandwidth)
    controller = RemoteController("c0", ip=controller_ip, port=controller_port)
    net = Mininet(topo=topo, switch=OVSSwitch, controller=controller, link=TCLink, autoSetMacs=True)

    try:
        net.start()
        net.pingAll()
        CLI(net)
    except KeyboardInterrupt:
        pass
    finally:
        net.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Diamond SDN Topology in Mininet")
    parser.add_argument("--controller-ip", default="127.0.0.1", help="Controller IP (default: 127.0.0.1)")
    parser.add_argument("--controller-port", type=int, default=6633, help="Controller port (default: 6633)")
    parser.add_argument("--bw", type=int, default=10, help="Link bandwidth in Mbps (default: 10)")
    args = parser.parse_args()
    run_diamond_network(args.controller_ip, args.controller_port, args.bw)


if __name__ == "__main__":
    main()
