"""Integrated Diagnostic and Topology Path Analysis Report.

Combines end-to-end network diagnostic measurements (RTT, jitter, packet loss)
with SDN-discovered topology and graph-based candidate path calculations.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from src.analysis.path_analysis import PathResult, TopologyGraph
except ImportError:
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
        """Convert report to dictionary format."""
        return {
            "source_ip": self.source_ip,
            "dest_ip": self.dest_ip,
            "diagnostic_summary": self.diagnostic_summary,
            "topology_summary": self.topology_summary,
            "candidate_paths": [p.to_dict() for p in self.candidate_paths],
            "disclaimers": [DISCLAIMER_FORWARDING_PATH, DISCLAIMER_RTT_MEASUREMENTS],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_text(self) -> str:
        """Format report into human-readable ASCII text."""
        border = "=" * 70
        diag = self.diagnostic_summary
        topo = self.topology_summary

        sent = diag.get("packets_sent", diag.get("sent", "N/A"))
        recv = diag.get("packets_received", diag.get("received", "N/A"))
        loss = diag.get("packet_loss_pct", diag.get("loss_pct", "0.0%"))
        loss_str = f"{loss:.2f}%" if isinstance(loss, (int, float)) else str(loss)

        def fmt_ms(val: Any) -> str:
            return f"{val:.3f} ms" if isinstance(val, (int, float)) else "N/A"

        lines = [
            border,
            "           INTEGRATED NETWORK DIAGNOSTIC & PATH REPORT",
            border,
            f"Source IP:      {self.source_ip}",
            f"Destination IP: {self.dest_ip}",
            "",
            "-" * 70,
            "1. END-TO-END DIAGNOSTIC SUMMARY",
            "-" * 70,
            f"  Packets:      Sent = {sent}, Received = {recv}, Loss = {loss_str}",
            f"  RTT Stats:    Min = {fmt_ms(diag.get('rtt_min_ms'))}, Avg = {fmt_ms(diag.get('rtt_avg_ms'))}, "
            f"Max = {fmt_ms(diag.get('rtt_max_ms'))}, Mdev = {fmt_ms(diag.get('rtt_mdev_ms', diag.get('jitter_ms')))}",
            "",
            "-" * 70,
            "2. DISCOVERED SDN TOPOLOGY",
            "-" * 70,
            f"  Switches ({len(topo.get('switches', []))} discovered):",
        ]

        for sw in topo.get("switches", []):
            ports = [str(p.get("port_no", "?")) for p in sw.get("ports", [])]
            p_desc = f"ports: [{', '.join(ports)}]" if ports else "no active ports"
            lines.append(f"    - DPID: {sw.get('dpid', 'unknown')} ({p_desc})")

        lines.append(f"  Links ({len(topo.get('links', []))} discovered):")
        for l in topo.get("links", []):
            lines.append(f"    - {l.get('src_dpid')}:{l.get('src_port')} <---> {l.get('dst_dpid')}:{l.get('dst_port')}")

        lines.append(f"  Hosts ({len(topo.get('hosts', []))} discovered):")
        for h in topo.get("hosts", []):
            ips = ", ".join(h.get("ipv4", [])) if isinstance(h.get("ipv4"), list) else str(h.get("ipv4"))
            lines.append(f"    - MAC: {h.get('mac')} | IP: {ips} | Attached to: {h.get('dpid')}:{h.get('port')}")

        lines.extend(["", "-" * 70, "3. CANDIDATE TOPOLOGY PATHS", "-" * 70])
        if not self.candidate_paths:
            lines.append("  No candidate paths found between source and destination.")
        else:
            lines.append(f"  Found {len(self.candidate_paths)} candidate path(s):")
            for idx, p in enumerate(self.candidate_paths, 1):
                star = " *** [SHORTEST PATH] ***" if p.is_shortest else ""
                lines.append(f"    Path #{idx} (hops={p.length}): {' -> '.join(p.path)}{star}")

        lines.extend([
            "",
            "-" * 70,
            "4. IMPORTANT NOTES & DISCLAIMERS",
            "-" * 70,
            f"  [*] {DISCLAIMER_FORWARDING_PATH}",
            f"  [*] {DISCLAIMER_RTT_MEASUREMENTS}",
            border,
        ])
        return "\n".join(lines)

    def save(self, filepath: str, output_format: str = "text") -> None:
        """Save report to file in specified format ('text' or 'json')."""
        content = self.to_json() if output_format.lower() == "json" else self.to_text()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)


def generate_report(
    diagnostic_results: Dict[str, Any],
    topology_data: Dict[str, Any],
    source_ip: str,
    dest_ip: str,
) -> DiagnosticReport:
    """Generate integrated DiagnosticReport from raw diagnostic and topology data."""
    graph = TopologyGraph()
    graph.build_from_topology_data(topology_data)
    paths = graph.get_paths_between_hosts(source_ip, dest_ip) or graph.find_all_paths(source_ip, dest_ip)

    return DiagnosticReport(
        source_ip=source_ip,
        dest_ip=dest_ip,
        diagnostic_summary=diagnostic_results,
        topology_summary=topology_data,
        candidate_paths=paths,
    )


def main() -> None:
    """CLI entrypoint for generating integrated diagnostic reports."""
    parser = argparse.ArgumentParser(description="Generate integrated network diagnostic and path report")
    parser.add_argument("--diagnostic", help="Path to diagnostic JSON file")
    parser.add_argument("--topology", help="Path to topology JSON file")
    parser.add_argument("--source", default="10.0.0.1", help="Source IP")
    parser.add_argument("--dest", default="10.0.0.2", help="Destination IP")
    parser.add_argument("--output", help="Save report to file")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    args = parser.parse_args()

    diag = {}
    if args.diagnostic:
        with open(args.diagnostic, "r", encoding="utf-8") as f:
            d = json.load(f)
            diag = {
                "packets_sent": d.get("probes_sent", 0),
                "packets_received": d.get("responses_received", 0),
                "packet_loss_pct": d.get("packet_loss_percent", 0.0),
                "rtt_min_ms": d.get("rtt_min_ms"),
                "rtt_avg_ms": d.get("rtt_avg_ms"),
                "rtt_max_ms": d.get("rtt_max_ms"),
                "rtt_mdev_ms": d.get("rtt_mdev_ms", d.get("jitter_ms")),
            }

    topo = {"switches": [], "links": [], "hosts": []}
    if args.topology:
        with open(args.topology, "r", encoding="utf-8") as f:
            topo = json.load(f)

    report = generate_report(diag, topo, args.source, args.dest)
    out = report.to_json() if args.format == "json" else report.to_text()
    print(out)

    if args.output:
        report.save(args.output, output_format=args.format)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
