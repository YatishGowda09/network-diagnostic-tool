"""UDP Diagnostic Client.

Sends periodic UDP probe packets to measure packet loss, RTT, and jitter.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("UDPClient")

DEFAULT_TARGET = "127.0.0.1"
DEFAULT_PORT = 5005
DEFAULT_COUNT = 10
DEFAULT_TIMEOUT = 1.0
DEFAULT_INTERVAL = 0.5
BUFFER_SIZE = 1024


class UDPClient:
    """Client for performing UDP latency and packet loss diagnostic probes."""

    def __init__(
        self,
        target: str = DEFAULT_TARGET,
        port: int = DEFAULT_PORT,
        count: int = DEFAULT_COUNT,
        timeout: float = DEFAULT_TIMEOUT,
        interval: float = DEFAULT_INTERVAL,
        output_file: Optional[str] = None,
    ) -> None:
        self.target = target
        self.port = port
        self.count = count
        self.timeout = timeout
        self.interval = interval
        self.output_file = output_file

        self.probes_sent = 0
        self.responses_received = 0
        self.seen_sequences: Set[int] = set()
        self.rtt_records: List[float] = []
        self.individual_results: List[Dict[str, Any]] = []

    def create_socket(self) -> socket.socket:
        """Create a configured UDP socket with probe timeout."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        return sock

    def build_probe_payload(self, seq: int) -> bytes:
        """Construct JSON probe packet (< 512 bytes)."""
        return json.dumps({
            "type": "probe",
            "seq": seq,
            "timestamp": time.time(),
            "payload": "DIAG",
        }).encode("utf-8")

    def parse_response(self, raw_data: bytes) -> Optional[Dict[str, Any]]:
        """Validate and parse incoming echo response."""
        try:
            data = json.loads(raw_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as err:
            logger.warning("Received malformed or non-JSON response: %s", err)
            return None

        if not isinstance(data, dict):
            logger.warning("Response payload is not a valid JSON object")
            return None

        if data.get("type") != "echo":
            logger.warning("Unexpected response type: %s", data.get("type"))
            return None

        if "seq" not in data or not isinstance(data["seq"], int):
            logger.warning("Response missing valid sequence number")
            return None

        return data

    def send_probe(self, sock: socket.socket, seq: int) -> Dict[str, Any]:
        """Send a single probe and wait for the matching echo response."""
        payload = self.build_probe_payload(seq)
        dest_addr = (self.target, self.port)
        t_start = time.monotonic()

        result: Dict[str, Any] = {
            "seq": seq,
            "status": "pending",
            "rtt_ms": None,
            "error": None,
            "server_timestamp": None,
        }

        try:
            sock.sendto(payload, dest_addr)
            self.probes_sent += 1

            while True:
                remaining_time = self.timeout - (time.monotonic() - t_start)
                if remaining_time <= 0:
                    raise socket.timeout()

                sock.settimeout(remaining_time)
                data, addr = sock.recvfrom(BUFFER_SIZE)
                t_end = time.monotonic()

                resp = self.parse_response(data)
                if resp is None:
                    continue

                resp_seq = resp["seq"]
                if resp_seq in self.seen_sequences:
                    logger.warning("Duplicate response received for sequence #%d from %s", resp_seq, addr)
                    continue

                if resp_seq == seq:
                    rtt_ms = (t_end - t_start) * 1000.0
                    self.seen_sequences.add(resp_seq)
                    self.responses_received += 1
                    self.rtt_records.append(rtt_ms)

                    result.update({
                        "status": "success",
                        "rtt_ms": round(rtt_ms, 3),
                        "server_timestamp": resp.get("server_timestamp"),
                    })
                    print(f"Probe #{seq:03d}: Reply from {addr[0]}:{addr[1]} bytes={len(data)} rtt={rtt_ms:.2f} ms")
                    break
                else:
                    logger.info("Received late response for seq #%d (expected #%d)", resp_seq, seq)
                    self.seen_sequences.add(resp_seq)

        except socket.timeout:
            result.update({"status": "timeout", "error": "Request timed out"})
            print(f"Probe #{seq:03d}: Request timed out (timeout={self.timeout:.1f}s)")
        except OSError as err:
            result.update({"status": "error", "error": str(err)})
            print(f"Probe #{seq:03d}: Network error - {err}")

        return result

    def calculate_statistics(self) -> Dict[str, Any]:
        """Compute summary statistics for all sent probes."""
        loss_pct = ((self.probes_sent - self.responses_received) / self.probes_sent * 100.0) if self.probes_sent > 0 else 0.0

        rtts = self.rtt_records
        min_rtt = min(rtts) if rtts else None
        max_rtt = max(rtts) if rtts else None
        avg_rtt = (sum(rtts) / len(rtts)) if rtts else None

        if len(rtts) >= 2:
            diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
            jitter = sum(diffs) / len(diffs)
        elif len(rtts) == 1:
            jitter = 0.0
        else:
            jitter = None

        return {
            "target": self.target,
            "port": self.port,
            "probes_sent": self.probes_sent,
            "responses_received": self.responses_received,
            "packet_loss_percent": round(loss_pct, 2),
            "rtt_min_ms": round(min_rtt, 3) if min_rtt is not None else None,
            "rtt_max_ms": round(max_rtt, 3) if max_rtt is not None else None,
            "rtt_avg_ms": round(avg_rtt, 3) if avg_rtt is not None else None,
            "jitter_ms": round(jitter, 3) if jitter is not None else None,
            "rtt_mdev_ms": round(jitter, 3) if jitter is not None else None,
            "individual_results": self.individual_results,
        }

    def print_summary(self, stats: Dict[str, Any]) -> None:
        """Display an ASCII summary table of probe session."""
        print(f"\n{'=' * 55}\n       UDP DIAGNOSTIC PROBE SUMMARY FOR {self.target}:{self.port}\n{'=' * 55}")
        print(f" Probes Transmitted      : {stats['probes_sent']}")
        print(f" Responses Received      : {stats['responses_received']}")
        print(f" Packet Loss Percentage  : {stats['packet_loss_percent']:.2f}%\n{'-' * 55}")
        if stats["rtt_avg_ms"] is not None:
            print(f" Minimum RTT             : {stats['rtt_min_ms']:.2f} ms")
            print(f" Maximum RTT             : {stats['rtt_max_ms']:.2f} ms")
            print(f" Average RTT             : {stats['rtt_avg_ms']:.2f} ms")
            if stats.get("jitter_ms") is not None:
                print(f" Jitter (mean deviation) : {stats['jitter_ms']:.2f} ms")
        else:
            print(" Round-Trip Time (RTT)   : N/A (100% packet loss)")
        print(f"{'=' * 55}\n")

    def save_output(self, stats: Dict[str, Any]) -> None:
        """Write summary results to JSON file if configured."""
        if not self.output_file:
            return
        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
            print(f"Results successfully saved to '{self.output_file}'")
        except OSError as err:
            logger.error("Failed to write output to '%s': %s", self.output_file, err)

    def run(self) -> Dict[str, Any]:
        """Execute the probe diagnostic session."""
        sock = self.create_socket()
        print(f"Starting UDP diagnostic probes to {self.target}:{self.port} ({self.count} probes, timeout={self.timeout}s, interval={self.interval}s)...\n")

        try:
            for seq in range(1, self.count + 1):
                self.individual_results.append(self.send_probe(sock, seq))
                if seq < self.count:
                    time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nProbing interrupted by user. Generating summary...")
        finally:
            sock.close()

        stats = self.calculate_statistics()
        self.print_summary(stats)
        self.save_output(stats)
        return stats


def parse_arguments() -> argparse.Namespace:
    """Parse CLI arguments for UDP diagnostic client."""
    parser = argparse.ArgumentParser(description="UDP Diagnostic Probe Client for RTT and Packet Loss Testing")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Target server IP or hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Target server UDP port")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Number of probes to send")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout per probe (s)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Interval between probes (s)")
    parser.add_argument("--output", default=None, help="Path to save JSON diagnostic results")
    return parser.parse_args()


def main() -> None:
    """CLI entry point for UDP diagnostic client."""
    args = parse_arguments()
    client = UDPClient(
        target=args.target,
        port=args.port,
        count=args.count,
        timeout=args.timeout,
        interval=args.interval,
        output_file=args.output,
    )
    client.run()


if __name__ == "__main__":
    main()
