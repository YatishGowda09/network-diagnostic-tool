#!/usr/bin/env python3
"""Automated Link Failure Injection and Dynamic SDN Rerouting Demonstration.

Demonstrates SDN resilience and dynamic path failover in the Mininet diamond topology:
1. Baseline Phase: Normal operation across primary path (s1 -> s2 -> s4).
2. Failure Phase: Link s1-s2 is programmatically taken down mid-stream.
   The Ryu SDN controller detects EventLinkDelete, purges stale flows,
   and dynamically reroutes UDP diagnostic probes through s3 (s1 -> s3 -> s4).
3. Recovery Phase: Link s1-s2 is restored, verifying path recovery.

Usage:
    # Live Mininet Run (Ubuntu VM with sudo):
    sudo python3 scripts/failover_demo.py

    # Standalone Simulation / Dry-run (Local host without Mininet/root):
    python3 scripts/failover_demo.py --mock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.diagnostic.udp_client import UDPClient
from src.diagnostic.udp_server import UDPServer
from src.sdn.controller import NetworkGraph


def run_live_mininet_demo(
    controller_ip: str = "127.0.0.1",
    controller_port: int = 6633,
    probes_per_phase: int = 15,
    output_file: str = "failover_demo_results.json",
) -> Dict[str, Any]:
    """Execute live Mininet failover experiment with real OVS and Ryu."""
    try:
        from mininet.link import TCLink
        from mininet.net import Mininet
        from mininet.node import OVSSwitch, RemoteController
        from topology.mininet_topology import DiamondTopo, inject_link_failure, restore_link
    except ImportError:
        print("[ERROR] Mininet is not installed in this Python environment.", file=sys.stderr)
        print("To run the live demo, execute inside an Ubuntu VM with Mininet.", file=sys.stderr)
        print("Alternatively, pass --mock to run the standalone simulation.", file=sys.stderr)
        sys.exit(1)

    if os.geteuid() != 0:
        print("[ERROR] Mininet requires root privileges. Please re-run with sudo:", file=sys.stderr)
        print(f"  sudo python3 {sys.argv[0]}", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("      LIVE MININET LINK FAILURE & DYNAMIC SDN REROUTING DEMO")
    print("=" * 70)

    # 1. Instantiate topology
    topo = DiamondTopo(bw=10)
    controller = RemoteController("c0", ip=controller_ip, port=controller_port)
    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=controller,
        link=TCLink,
        autoSetMacs=True,
    )

    results: Dict[str, Any] = {
        "timestamp": time.time(),
        "mode": "live_mininet",
        "phases": {},
    }

    try:
        print("\n[*] Starting Mininet virtual network...")
        net.start()
        time.sleep(2)  # Allow OpenFlow handshakes to settle

        h1 = net.get("h1")
        h2 = net.get("h2")

        # Start UDP echo server on h2
        print(f"[*] Starting UDP echo server on h2 ({h2.IP()}:5005)...")
        h2.cmd("python3 src/diagnostic/udp_server.py --host 10.0.0.2 --port 5005 &")
        time.sleep(1)

        # Phase 1: Baseline
        print("\n" + "=" * 60)
        print(" PHASE 1: Baseline Probes (Upper Path: s1 -> s2 -> s4)")
        print("=" * 60)
        cmd_p1 = (
            f"python3 src/diagnostic/udp_client.py --target 10.0.0.2 --port 5005 "
            f"--count {probes_per_phase} --interval 0.2 --output /tmp/phase1.json"
        )
        print(h1.cmd(cmd_p1))
        with open("/tmp/phase1.json", "r") as f:
            results["phases"]["baseline"] = json.load(f)

        # Phase 2: Inject Link Failure
        print("\n" + "=" * 60)
        print(" PHASE 2: Fault Injection — Disabling link s1 <---> s2")
        print("=" * 60)
        inject_link_failure(net, "s1", "s2")
        print("[*] Waiting 1.0s for Ryu EventLinkDelete and dynamic reroute...")
        time.sleep(1.0)

        cmd_p2 = (
            f"python3 src/diagnostic/udp_client.py --target 10.0.0.2 --port 5005 "
            f"--count {probes_per_phase} --interval 0.2 --output /tmp/phase2.json"
        )
        print(h1.cmd(cmd_p2))
        with open("/tmp/phase2.json", "r") as f:
            results["phases"]["failover_active"] = json.load(f)

        # Phase 3: Restore Link
        print("\n" + "=" * 60)
        print(" PHASE 3: Fault Recovery — Restoring link s1 <---> s2")
        print("=" * 60)
        restore_link(net, "s1", "s2")
        print("[*] Waiting 1.0s for Ryu EventLinkAdd...")
        time.sleep(1.0)

        cmd_p3 = (
            f"python3 src/diagnostic/udp_client.py --target 10.0.0.2 --port 5005 "
            f"--count {probes_per_phase} --interval 0.2 --output /tmp/phase3.json"
        )
        print(h1.cmd(cmd_p3))
        with open("/tmp/phase3.json", "r") as f:
            results["phases"]["recovered"] = json.load(f)

    finally:
        print("\n[*] Stopping Mininet network and cleaning up...")
        net.stop()
        os.system("pkill -f udp_server.py 2>/dev/null")

    # Save results
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[+] Demonstration results successfully saved to '{output_file}'")
    return results


def run_mock_simulation_demo(
    probes_per_phase: int = 15,
    output_file: str = "failover_demo_results.json",
) -> Dict[str, Any]:
    """Execute standalone loopback simulation of the 3-phase failover demo."""
    print("=" * 70)
    print("      STANDALONE LINK FAILURE & DYNAMIC SDN REROUTING SIMULATION")
    print("=" * 70)
    print("Simulating diamond topology with dynamic graph path recalculation:\n")

    graph = NetworkGraph()
    graph.add_link(1, 1, 2, 1)
    graph.add_link(1, 2, 3, 1)
    graph.add_link(2, 2, 4, 1)
    graph.add_link(3, 2, 4, 2)
    graph.add_host("00:00:00:00:00:01", 1, 3, "10.0.0.1")
    graph.add_host("00:00:00:00:00:02", 4, 3, "10.0.0.2")

    results: Dict[str, Any] = {
        "timestamp": time.time(),
        "mode": "standalone_simulation",
        "phases": {},
    }

    # Phase 1: Baseline
    p1_path = graph.shortest_path(1, 4)
    print("=" * 60)
    print(f" PHASE 1: Baseline Diamond Path: {' -> '.join(f's{d}' for d in p1_path)}")
    print("=" * 60)
    results["phases"]["baseline"] = {
        "active_path": [f"s{d}" for d in p1_path],
        "path_hops": len(p1_path) - 1,
        "probes_sent": probes_per_phase,
        "responses_received": probes_per_phase,
        "packet_loss_percent": 0.0,
        "rtt_min_ms": 0.84,
        "rtt_avg_ms": 1.45,
        "rtt_max_ms": 2.31,
        "jitter_ms": 0.41,
        "status": "HEALTHY",
    }
    print(f"  Forwarding Path : {' -> '.join(f's{d}' for d in p1_path)} (Upper branch)")
    print(f"  Probes Sent     : {probes_per_phase} / {probes_per_phase} received")
    print("  Packet Loss     : 0.00%")
    print("  Average RTT     : 1.45 ms (Jitter: 0.41 ms)")

    # Phase 2: Injected Failure
    print("\n" + "=" * 60)
    print(" PHASE 2: Injected Fault — Link s1 <---> s2 set to DOWN")
    print("=" * 60)
    graph.remove_link(1, 2)
    p2_path = graph.shortest_path(1, 4)
    print(f"  [CONTROLLER] EventLinkDelete triggered for s1:1 <-> s2:1")
    print(f"  [CONTROLLER] Purged stale OpenFlow flows on s1:1 and s2:1")
    print(f"  [CONTROLLER] Recalculated shortest path -> {' -> '.join(f's{d}' for d in p2_path)}")

    results["phases"]["failover_active"] = {
        "active_path": [f"s{d}" for d in p2_path],
        "path_hops": len(p2_path) - 1,
        "probes_sent": probes_per_phase,
        "responses_received": probes_per_phase - 1,
        "packet_loss_percent": round(100.0 / probes_per_phase, 2),
        "rtt_min_ms": 0.98,
        "rtt_avg_ms": 1.72,
        "rtt_max_ms": 3.10,
        "jitter_ms": 0.58,
        "status": "FAILOVER_REROUTED",
    }
    print(f"  Forwarding Path : {' -> '.join(f's{d}' for d in p2_path)} (Lower branch)")
    print(f"  Probes Sent     : {probes_per_phase} ({probes_per_phase - 1} received, 1 transient drop during cut)")
    print(f"  Packet Loss     : {results['phases']['failover_active']['packet_loss_percent']:.2f}% (Quick recovery)")
    print("  Average RTT     : 1.72 ms (Jitter: 0.58 ms)")

    # Phase 3: Restoration
    print("\n" + "=" * 60)
    print(" PHASE 3: Fault Recovery — Link s1 <---> s2 RESTORED")
    print("=" * 60)
    graph.add_link(1, 1, 2, 1)
    p3_path = graph.shortest_path(1, 4)
    print(f"  [CONTROLLER] EventLinkAdd triggered for s1:1 <-> s2:1")
    print(f"  [CONTROLLER] Restored primary path -> {' -> '.join(f's{d}' for d in p3_path)}")

    results["phases"]["recovered"] = {
        "active_path": [f"s{d}" for d in p3_path],
        "path_hops": len(p3_path) - 1,
        "probes_sent": probes_per_phase,
        "responses_received": probes_per_phase,
        "packet_loss_percent": 0.0,
        "rtt_min_ms": 0.81,
        "rtt_avg_ms": 1.38,
        "rtt_max_ms": 2.15,
        "jitter_ms": 0.38,
        "status": "RESTORED",
    }
    print(f"  Forwarding Path : {' -> '.join(f's{d}' for d in p3_path)} (Upper branch)")
    print(f"  Probes Sent     : {probes_per_phase} / {probes_per_phase} received")
    print("  Packet Loss     : 0.00%")
    print("  Average RTT     : 1.38 ms (Jitter: 0.38 ms)")

    # Summary table
    print("\n" + "=" * 70)
    print("                     FAILOVER COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'PHASE':<18} {'ACTIVE PATH':<18} {'LOSS %':<10} {'AVG RTT':<12} {'JITTER'}")
    print("-" * 70)
    for name, pdata in results["phases"].items():
        p_str = " -> ".join(pdata["active_path"])
        loss = f"{pdata['packet_loss_percent']:.2f}%"
        avg_rtt = f"{pdata['rtt_avg_ms']:.2f} ms"
        jit = f"{pdata['jitter_ms']:.2f} ms"
        print(f"{name:<18} {p_str:<18} {loss:<10} {avg_rtt:<12} {jit}")
    print("=" * 70 + "\n")

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[+] Simulation results successfully saved to '{output_file}'")
    return results


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Automated Link Failure Injection & SDN Rerouting Demonstration"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run standalone simulation mode (default when root/Mininet unavailable)",
    )
    parser.add_argument(
        "--probes",
        type=int,
        default=15,
        help="Probes to transmit per phase (default: 15)",
    )
    parser.add_argument(
        "--output",
        default="failover_demo_results.json",
        help="Output JSON file for results (default: failover_demo_results.json)",
    )
    parser.add_argument(
        "--controller-ip",
        default="127.0.0.1",
        help="Remote SDN controller IP (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--controller-port",
        type=int,
        default=6633,
        help="Remote SDN controller OpenFlow port (default: 6633)",
    )
    args = parser.parse_args()

    # Auto-detect whether to use mock or live Mininet
    can_run_live = os.geteuid() == 0 and not args.mock
    try:
        import mininet
    except ImportError:
        can_run_live = False

    if can_run_live:
        run_live_mininet_demo(
            controller_ip=args.controller_ip,
            controller_port=args.controller_port,
            probes_per_phase=args.probes,
            output_file=args.output,
        )
    else:
        run_mock_simulation_demo(
            probes_per_phase=args.probes,
            output_file=args.output,
        )


if __name__ == "__main__":
    main()
