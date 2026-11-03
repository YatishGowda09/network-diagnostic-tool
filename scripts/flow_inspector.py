#!/usr/bin/env python3
"""OpenFlow Flow Table Inspector.

Inspects and displays active OpenFlow 1.3 flow table rules across Open vSwitch
nodes in the Mininet diamond topology using `ovs-ofctl`. Identifies which
forwarding path is actively routing UDP diagnostic and L2 traffic.

Usage:
    sudo python3 scripts/flow_inspector.py
    python3 scripts/flow_inspector.py --mock   # Demonstration without root/OVS
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional


DEFAULT_SWITCHES = ["s1", "s2", "s3", "s4"]


def query_ovs_flows(switch: str) -> Optional[str]:
    """Execute `ovs-ofctl dump-flows` on a given switch.

    Args:
        switch: Switch name (e.g., 's1').

    Returns:
        Raw string output from ovs-ofctl, or None if command fails.
    """
    cmd = ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as err:
        return None


def parse_flow_lines(raw_output: str) -> List[Dict[str, Any]]:
    """Parse raw ovs-ofctl flow output into structured flow rule dictionaries.

    Args:
        raw_output: Standard stdout from `ovs-ofctl dump-flows`.

    Returns:
        List of parsed flow dictionaries.
    """
    flows: List[Dict[str, Any]] = []

    for line in raw_output.splitlines():
        line = line.strip()
        if not line or line.startswith("NXST") or line.startswith("OFPST"):
            continue

        flow_info: Dict[str, Any] = {
            "priority": "0",
            "table": "0",
            "packets": "0",
            "bytes": "0",
            "match": "all",
            "actions": "",
            "raw": line,
        }

        # Parse key fields
        m_priority = re.search(r"priority=(\d+)", line)
        if m_priority:
            flow_info["priority"] = m_priority.group(1)

        m_packets = re.search(r"n_packets=(\d+)", line)
        if m_packets:
            flow_info["packets"] = m_packets.group(1)

        m_bytes = re.search(r"n_bytes=(\d+)", line)
        if m_bytes:
            flow_info["bytes"] = m_bytes.group(1)

        # Actions are at the end: "actions=..."
        if "actions=" in line:
            parts = line.split("actions=", 1)
            flow_info["actions"] = parts[1]
            match_part = parts[0]
            # Match is everything after priority or table
            m_match = re.search(r"priority=\d+,?(.*)", match_part)
            if m_match and m_match.group(1):
                clean_match = m_match.group(1).rstrip(", ")
                flow_info["match"] = clean_match if clean_match else "any"
            else:
                flow_info["match"] = "table-miss (all)"

        flows.append(flow_info)

    return flows


def get_mock_flows() -> Dict[str, List[Dict[str, Any]]]:
    """Generate synthetic flow tables representing diamond topology active state."""
    return {
        "s1": [
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:01,eth_dst=00:00:00:00:00:02",
                "actions": "output:1 (to s2)",
            },
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:02,eth_dst=00:00:00:00:00:01",
                "actions": "output:3 (to h1)",
            },
            {
                "priority": "0",
                "packets": "8",
                "bytes": "624",
                "match": "table-miss (all)",
                "actions": "CONTROLLER:65535",
            },
        ],
        "s2": [
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:01,eth_dst=00:00:00:00:00:02",
                "actions": "output:2 (to s4)",
            },
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:02,eth_dst=00:00:00:00:00:01",
                "actions": "output:1 (to s1)",
            },
            {
                "priority": "0",
                "packets": "2",
                "bytes": "156",
                "match": "table-miss (all)",
                "actions": "CONTROLLER:65535",
            },
        ],
        "s3": [
            {
                "priority": "0",
                "packets": "0",
                "bytes": "0",
                "match": "table-miss (all)",
                "actions": "CONTROLLER:65535 (Idle backup path)",
            },
        ],
        "s4": [
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:01,eth_dst=00:00:00:00:00:02",
                "actions": "output:3 (to h2)",
            },
            {
                "priority": "10",
                "packets": "42",
                "bytes": "4956",
                "match": "eth_src=00:00:00:00:00:02,eth_dst=00:00:00:00:00:01",
                "actions": "output:1 (to s2)",
            },
            {
                "priority": "0",
                "packets": "5",
                "bytes": "390",
                "match": "table-miss (all)",
                "actions": "CONTROLLER:65535",
            },
        ],
    }


def display_switch_flows(switch: str, flows: List[Dict[str, Any]]) -> None:
    """Print formatted flow table for a switch."""
    print("\n" + "=" * 76)
    print(f" Switch [{switch}] OpenFlow 1.3 Flow Table ({len(flows)} rules installed)")
    print("=" * 76)
    print(f"{'PRIO':<6} {'PACKETS':<9} {'BYTES':<10} {'MATCH':<30} {'ACTION'}")
    print("-" * 76)

    for flow in flows:
        prio = flow.get("priority", "0")
        pkts = flow.get("packets", "0")
        b = flow.get("bytes", "0")
        match = flow.get("match", "any")
        if len(match) > 28:
            match = match[:25] + "..."
        act = flow.get("actions", "")
        print(f"{prio:<6} {pkts:<9} {b:<10} {match:<30} {act}")


def infer_active_forwarding_path(all_flows: Dict[str, List[Dict[str, Any]]]) -> str:
    """Infer whether upper path (s2) or lower path (s3) is forwarding traffic."""
    s2_packets = 0
    s3_packets = 0

    for flow in all_flows.get("s2", []):
        if flow.get("priority") != "0":
            s2_packets += int(flow.get("packets", 0))

    for flow in all_flows.get("s3", []):
        if flow.get("priority") != "0":
            s3_packets += int(flow.get("packets", 0))

    if s2_packets > 0 and s3_packets == 0:
        return "PRIMARY PATH (Upper): h1 <-> s1 <-> s2 <-> s4 <-> h2"
    elif s3_packets > 0 and s2_packets == 0:
        return "REROUTED PATH (Lower): h1 <-> s1 <-> s3 <-> s4 <-> h2 (Failover Active)"
    elif s2_packets > 0 and s3_packets > 0:
        return f"MULTIPATH / LOAD BALANCING (s2 pkts: {s2_packets}, s3 pkts: {s3_packets})"
    else:
        return "NO ACTIVE FLOWS (Default table-miss only)"


def main() -> None:
    """CLI entrypoint for flow inspection."""
    parser = argparse.ArgumentParser(
        description="OpenFlow 1.3 Flow Table Inspector for Mininet Diamond Topology"
    )
    parser.add_argument(
        "--switches",
        nargs="+",
        default=DEFAULT_SWITCHES,
        help="List of switches to inspect (default: s1 s2 s3 s4)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Display synthetic flow tables (for offline demo or testing without root)",
    )
    args = parser.parse_args()

    ovs_present = shutil.which("ovs-ofctl") is not None
    use_mock = args.mock or not ovs_present or os.geteuid() != 0

    if use_mock:
        if not args.mock and not ovs_present:
            print("[INFO] ovs-ofctl not found on host. Displaying demonstration flow tables:")
        elif not args.mock and os.geteuid() != 0:
            print("[INFO] Running without root privileges. Displaying demonstration flow tables:")
            print("       (To inspect live Open vSwitch flows, re-run with: sudo python3 scripts/flow_inspector.py)\n")
        all_flows = get_mock_flows()
    else:
        all_flows = {}
        for sw in args.switches:
            raw = query_ovs_flows(sw)
            if raw is not None:
                all_flows[sw] = parse_flow_lines(raw)
            else:
                all_flows[sw] = []

    for sw in args.switches:
        flows = all_flows.get(sw, [])
        display_switch_flows(sw, flows)

    print("\n" + "=" * 76)
    print("                    DATA-PLANE PATH INFERENCE")
    print("=" * 76)
    print(f"Forwarding Path: {infer_active_forwarding_path(all_flows)}")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    main()
