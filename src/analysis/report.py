"""Integrated Diagnostic and Topology Path Analysis Report.

Combines end-to-end network diagnostic measurements (RTT, jitter, packet loss)
with SDN-discovered topology and graph-based candidate path calculations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

try:
    from src.analysis.path_analysis import PathResult, TopologyGraph
except ImportError:
    # Handle direct invocation or flat module paths
    from path_analysis import PathResult, TopologyGraph  # type: ignore


DISCLAIMER_FORWARDING_PATH = (
    "DISCLAIMER: Candidate paths are computed from topology graph. "
    "Actual forwarding path depends on controller flow rules."
)

DISCLAIMER_RTT_MEASUREMENTS = (
    "DISCLAIMER: End-to-end RTT measurements do not reveal per-link delays."
)


@dataclass
class DiagnosticReport:
    """Aggregated network diagnostic and topology report."""

    source_ip: str
    dest_ip: str
    diagnostic_summary: Dict[str, Any]
    topology_summary: Dict[str, Any]
    candidate_paths: List[PathResult]

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "source_ip": self.source_ip,
            "dest_ip": self.dest_ip,
            "diagnostic_summary": self.diagnostic_summary,
            "topology_summary": self.topology_summary,
            "candidate_paths": [p.to_dict() for p in self.candidate_paths],
            "disclaimers": [
                DISCLAIMER_FORWARDING_PATH,
                DISCLAIMER_RTT_MEASUREMENTS,
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_text(self) -> str:
        """Format report into human-readable text."""
        lines: List[str] = []
        border = "=" * 70

        lines.append(border)
        lines.append("           INTEGRATED NETWORK DIAGNOSTIC & PATH REPORT")
        lines.append(border)
        lines.append(f"Source IP:      {self.source_ip}")
        lines.append(f"Destination IP: {self.dest_ip}")
        lines.append("")

        # 1. Diagnostic Summary Section
        lines.append("-" * 70)
        lines.append("1. END-TO-END DIAGNOSTIC SUMMARY")
        lines.append("-" * 70)
        diag = self.diagnostic_summary
        sent = diag.get("packets_sent", diag.get("sent", "N/A"))
        recv = diag.get("packets_received", diag.get("received", "N/A"))
        loss = diag.get("packet_loss_pct", diag.get("loss_pct", "0.0%"))
        if isinstance(loss, (int, float)):
            loss_str = f"{loss:.2f}%"
        else:
            loss_str = str(loss)

        lines.append(f"  Packets:      Sent = {sent}, Received = {recv}, Loss = {loss_str}")

        rtt_min = diag.get("rtt_min_ms", diag.get("min_rtt_ms"))
        rtt_avg = diag.get("rtt_avg_ms", diag.get("avg_rtt_ms"))
        rtt_max = diag.get("rtt_max_ms", diag.get("max_rtt_ms"))
        rtt_mdev = diag.get("rtt_mdev_ms", diag.get("mdev_ms", diag.get("jitter_ms")))

        def fmt_val(val: Any) -> str:
            return f"{val:.3f} ms" if isinstance(val, (int, float)) else "N/A"

        lines.append(
            f"  RTT Stats:    Min = {fmt_val(rtt_min)}, Avg = {fmt_val(rtt_avg)}, "
            f"Max = {fmt_val(rtt_max)}, Mdev = {fmt_val(rtt_mdev)}"
        )
        lines.append("")

        # 2. Discovered Topology Section
        lines.append("-" * 70)
        lines.append("2. DISCOVERED SDN TOPOLOGY")
        lines.append("-" * 70)
        topo = self.topology_summary
        switches = topo.get("switches", [])
        links = topo.get("links", [])
        hosts = topo.get("hosts", [])

        lines.append(f"  Switches ({len(switches)} discovered):")
        for sw in switches:
            dpid = sw.get("dpid", "unknown")
            ports = [str(p.get("port_no", "?")) for p in sw.get("ports", [])]
            ports_desc = f"ports: [{', '.join(ports)}]" if ports else "no active ports"
            lines.append(f"    - DPID: {dpid} ({ports_desc})")

        lines.append(f"  Links ({len(links)} discovered):")
        for link in links:
            src = f"{link.get('src_dpid')}:{link.get('src_port')}"
            dst = f"{link.get('dst_dpid')}:{link.get('dst_port')}"
            lines.append(f"    - {src} <---> {dst}")

        lines.append(f"  Hosts ({len(hosts)} discovered):")
        for h in hosts:
            mac = h.get("mac", "")
            ips = h.get("ipv4", [])
            ip_str = ", ".join(ips) if isinstance(ips, list) else str(ips)
            attached = f"{h.get('dpid')}:{h.get('port')}"
            lines.append(f"    - MAC: {mac} | IP: {ip_str} | Attached to: {attached}")
        lines.append("")

        # 3. Path Analysis Section
        lines.append("-" * 70)
        lines.append("3. CANDIDATE TOPOLOGY PATHS")
        lines.append("-" * 70)
        if not self.candidate_paths:
            lines.append("  No candidate paths found between source and destination.")
        else:
            lines.append(f"  Found {len(self.candidate_paths)} candidate path(s):")
            for idx, path_res in enumerate(self.candidate_paths, 1):
                path_str = " -> ".join(path_res.path)
                shortest_marker = " *** [SHORTEST PATH] ***" if path_res.is_shortest else ""
                lines.append(f"    Path #{idx} (hops={path_res.length}): {path_str}{shortest_marker}")
        lines.append("")

        # 4. Critical Engineering Disclaimers
        lines.append("-" * 70)
        lines.append("4. IMPORTANT NOTES & DISCLAIMERS")
        lines.append("-" * 70)
        lines.append(f"  [*] {DISCLAIMER_FORWARDING_PATH}")
        lines.append(f"  [*] {DISCLAIMER_RTT_MEASUREMENTS}")
        lines.append(border)

        return "\n".join(lines)

    def save(self, filepath: str, output_format: str = "text") -> None:
        """Save report to file in specified format ('text' or 'json').

        Args:
            filepath: Path to save output file.
            output_format: 'text' or 'json' (default: 'text').
        """
        content = self.to_json() if output_format.lower() == "json" else self.to_text()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)


def generate_report(
    diagnostic_results: Dict[str, Any],
    topology_data: Dict[str, Any],
    source_ip: str,
    dest_ip: str,
) -> DiagnosticReport:
    """Generate integrated DiagnosticReport from raw diagnostic and topology data.

    Args:
        diagnostic_results: Dictionary containing RTT stats, packet loss, etc.
        topology_data: Dictionary containing switches, links, and hosts.
        source_ip: Source host IP address.
        dest_ip: Destination host IP address.

    Returns:
        Populated DiagnosticReport instance.
    """
    graph = TopologyGraph()
    graph.build_from_topology_data(topology_data)

    candidate_paths = graph.get_paths_between_hosts(source_ip, dest_ip)

    # If hosts were not mapped by IP directly in topology_data, attempt node resolution
    if not candidate_paths:
        candidate_paths = graph.find_all_paths(source_ip, dest_ip)

    return DiagnosticReport(
        source_ip=source_ip,
        dest_ip=dest_ip,
        diagnostic_summary=diagnostic_results,
        topology_summary=topology_data,
        candidate_paths=candidate_paths,
    )


def main() -> None:
    """CLI entrypoint for generating integrated diagnostic reports.

    Supports two modes:
    1. With --diagnostic and --topology JSON files: generates report from real data
    2. Without arguments: generates sample demonstration report
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate integrated network diagnostic and path analysis report"
    )
    parser.add_argument(
        "--diagnostic",
        type=str,
        default=None,
        help="Path to diagnostic results JSON file (from udp_client.py --output)",
    )
    parser.add_argument(
        "--topology",
        type=str,
        default=None,
        help="Path to topology JSON file (from topology.py --save)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="10.0.0.1",
        help="Source host IP address (default: 10.0.0.1)",
    )
    parser.add_argument(
        "--dest",
        type=str,
        default="10.0.0.2",
        help="Destination host IP address (default: 10.0.0.2)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save report to file (default: print to stdout)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    # Load diagnostic results
    if args.diagnostic:
        try:
            with open(args.diagnostic, "r", encoding="utf-8") as f:
                diagnostic_data = json.load(f)
            # Map udp_client.py field names to report field names
            diagnostic_results = {
                "packets_sent": diagnostic_data.get("probes_sent", 0),
                "packets_received": diagnostic_data.get("responses_received", 0),
                "packet_loss_pct": diagnostic_data.get("packet_loss_percent", 0.0),
                "rtt_min_ms": diagnostic_data.get("rtt_min_ms"),
                "rtt_avg_ms": diagnostic_data.get("rtt_avg_ms"),
                "rtt_max_ms": diagnostic_data.get("rtt_max_ms"),
            }
        except (OSError, json.JSONDecodeError) as err:
            print(f"Error loading diagnostic file: {err}")
            return
    else:
        # Sample data for demonstration
        diagnostic_results = {
            "packets_sent": 10,
            "packets_received": 10,
            "packet_loss_pct": 0.0,
            "rtt_min_ms": 0.842,
            "rtt_avg_ms": 1.450,
            "rtt_max_ms": 2.310,
            "rtt_mdev_ms": 0.412,
        }

    # Load topology data
    if args.topology:
        try:
            with open(args.topology, "r", encoding="utf-8") as f:
                topology_data = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            print(f"Error loading topology file: {err}")
            return
    else:
        # Sample diamond topology for demonstration
        topology_data = {
            "switches": [
                {"dpid": "0000000000000001", "ports": [{"port_no": 1}, {"port_no": 2}, {"port_no": 3}]},
                {"dpid": "0000000000000002", "ports": [{"port_no": 1}, {"port_no": 2}]},
                {"dpid": "0000000000000003", "ports": [{"port_no": 1}, {"port_no": 2}]},
                {"dpid": "0000000000000004", "ports": [{"port_no": 1}, {"port_no": 2}, {"port_no": 3}]},
            ],
            "links": [
                {"src_dpid": "0000000000000001", "src_port": 1, "dst_dpid": "0000000000000002", "dst_port": 1},
                {"src_dpid": "0000000000000001", "src_port": 2, "dst_dpid": "0000000000000003", "dst_port": 1},
                {"src_dpid": "0000000000000002", "src_port": 2, "dst_dpid": "0000000000000004", "dst_port": 1},
                {"src_dpid": "0000000000000003", "src_port": 2, "dst_dpid": "0000000000000004", "dst_port": 2},
            ],
            "hosts": [
                {"mac": "00:00:00:00:00:01", "ipv4": ["10.0.0.1"], "dpid": "0000000000000001", "port": 3},
                {"mac": "00:00:00:00:00:02", "ipv4": ["10.0.0.2"], "dpid": "0000000000000004", "port": 3},
            ],
        }

    report = generate_report(
        diagnostic_results=diagnostic_results,
        topology_data=topology_data,
        source_ip=args.source,
        dest_ip=args.dest,
    )

    # Output the report
    if args.format == "json":
        output = report.to_json()
    else:
        output = report.to_text()

    print(output)

    if args.output:
        report.save(args.output, output_format=args.format)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
