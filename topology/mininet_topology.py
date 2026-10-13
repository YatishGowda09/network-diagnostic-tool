"""Mininet Diamond (Rhombus) Topology for SDN Testing.

This script creates a 4-switch diamond topology with 2 end hosts in Mininet:
                 +-------+
             +-->|  s2   |---+
             |   +-------+   |
  +----+   +-+-+           +-v-+   +----+
  | h1 |---> s1 |           | s4 |--> h2 |
  +----+   +-+-+           +-^-+   +----+
             |   +-------+   |
             +-->|  s3   |---+
                 +-------+

Hosts:
  - h1: 10.0.0.1/24 (connected to s1)
  - h2: 10.0.0.2/24 (connected to s4)

Switches:
  - s1, s2, s3, s4 using Open vSwitch (OVSSwitch) configured for OpenFlow 1.3
  - Connects to RemoteController (default: 127.0.0.1:6633)
  - Links configured with traffic control (default 10 Mbps bandwidth)
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
    # Placeholder classes for static analysis and environments without Mininet
    class Topo:  # type: ignore
        """Dummy Topo base class."""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


if MININET_AVAILABLE:
    class DiamondTopo(Topo):
        """Diamond topology with 4 switches and 2 hosts."""

        def build(self, bw: int = 10, **kwargs: Any) -> None:
            """Build diamond topology with specified link bandwidth in Mbps."""
            # Add switches configured for OpenFlow 1.3
            s1 = self.addSwitch("s1", protocols="OpenFlow13")
            s2 = self.addSwitch("s2", protocols="OpenFlow13")
            s3 = self.addSwitch("s3", protocols="OpenFlow13")
            s4 = self.addSwitch("s4", protocols="OpenFlow13")

            # Add end hosts
            h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
            h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

            # Host links
            self.addLink(h1, s1, bw=bw)
            self.addLink(h2, s4, bw=bw)

            # Inter-switch links forming diamond paths:
            # Path A: s1 -> s2 -> s4
            # Path B: s1 -> s3 -> s4
            self.addLink(s1, s2, bw=bw)
            self.addLink(s1, s3, bw=bw)
            self.addLink(s2, s4, bw=bw)
            self.addLink(s3, s4, bw=bw)


def print_topology_info(controller_ip: str, controller_port: int, bw: int) -> None:
    """Print summary banner of the diamond topology configuration."""
    print("=" * 65)
    print("           MININET DIAMOND (RHOMBUS) TOPOLOGY")
    print("=" * 65)
    print(f"Controller:      RemoteController at {controller_ip}:{controller_port}")
    print(f"OpenFlow Ver:    OpenFlow 1.3 (OVSSwitch)")
    print(f"Link Bandwidth:  {bw} Mbps (TCLink)")
    print("\nNetwork Nodes & Links:")
    print("  Host 1:        h1 (10.0.0.1, 00:00:00:00:00:01) -> s1")
    print("  Host 2:        h2 (10.0.0.2, 00:00:00:00:00:02) -> s4")
    print("  Diamond paths: s1 -> s2 -> s4 (Upper branch)")
    print("                 s1 -> s3 -> s4 (Lower branch)")
    print("=" * 65)


def run_diamond_network(
    controller_ip: str = "127.0.0.1",
    controller_port: int = 6633,
    bandwidth: int = 10,
) -> None:
    """Instantiate and start Mininet network with diamond topology.

    Args:
        controller_ip: IP address of remote SDN controller
        controller_port: OpenFlow port of remote controller
        bandwidth: Link bandwidth in Mbps
    """
    if not MININET_AVAILABLE:
        print("ERROR: Mininet is not installed in this Python environment.", file=sys.stderr)
        print("Please run this script inside an environment/VM where Mininet is available.", file=sys.stderr)
        sys.exit(1)

    if os.geteuid() != 0:
        print("ERROR: Mininet requires root privileges. Please re-run with sudo:", file=sys.stderr)
        print(f"  sudo python3 {sys.argv[0]}", file=sys.stderr)
        sys.exit(1)

    setLogLevel("info")
    print_topology_info(controller_ip, controller_port, bandwidth)

    topo = DiamondTopo(bw=bandwidth)
    controller = RemoteController("c0", ip=controller_ip, port=controller_port)

    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=controller,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False,
    )

    try:
        info("*** Starting network\n")
        net.start()

        info("*** Testing connectivity between hosts\n")
        net.pingAll()

        info("*** Starting Mininet CLI (type 'exit' or Ctrl+D to quit)\n")
        CLI(net)
    except KeyboardInterrupt:
        info("\n*** Interrupted by user\n")
    finally:
        info("*** Stopping network\n")
        net.stop()
        info("*** Cleaned up Mininet network\n")


def main() -> None:
    """Parse command line arguments and execute Mininet topology."""
    parser = argparse.ArgumentParser(
        description="Run Diamond SDN Topology in Mininet"
    )
    parser.add_argument(
        "--controller-ip",
        default="127.0.0.1",
        help="Remote SDN controller IP address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--controller-port",
        type=int,
        default=6633,
        help="Remote SDN controller OpenFlow port (default: 6633)",
    )
    parser.add_argument(
        "--bw",
        type=int,
        default=10,
        help="Link bandwidth in Mbps (default: 10)",
    )

    args = parser.parse_args()
    run_diamond_network(
        controller_ip=args.controller_ip,
        controller_port=args.controller_port,
        bandwidth=args.bw,
    )


if __name__ == "__main__":
    main()
