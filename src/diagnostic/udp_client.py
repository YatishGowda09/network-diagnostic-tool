"""UDP Diagnostic Client.

Sends periodic UDP probe packets to a target host and port to measure
packet loss, network latency, and round-trip time (RTT) statistics.
"""

import argparse
import json
import logging
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Set

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("UDPClient")

DEFAULT_TARGET: str = "127.0.0.1"
DEFAULT_PORT: int = 5005
DEFAULT_COUNT: int = 10
DEFAULT_TIMEOUT: float = 1.0
DEFAULT_INTERVAL: float = 0.5
BUFFER_SIZE: int = 1024


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
        """Initialize the UDP diagnostic client.

        Args:
            target: Destination IP address or hostname.
            port: Destination UDP port.
            count: Number of probes to transmit.
            timeout: Maximum wait time in seconds for each probe response.
            interval: Pause duration in seconds between consecutive probes.
            output_file: Path to optional JSON output report file.
        """
        self.target: str = target
        self.port: int = port
        self.count: int = count
        self.timeout: float = timeout
        self.interval: float = interval
        self.output_file: Optional[str] = output_file

        self.probes_sent: int = 0
        self.responses_received: int = 0
        self.seen_sequences: Set[int] = set()
        self.rtt_records: List[float] = []
        self.individual_results: List[Dict[str, Any]] = []

    def create_socket(self) -> socket.socket:
        """Create a UDP socket configured with probe timeout.

        Returns:
            A configured UDP socket.
        """
        # socket.AF_INET specifies IPv4 addressing.
        # socket.SOCK_DGRAM specifies UDP datagram communication.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        return sock

    def build_probe_payload(self, seq: int) -> bytes:
        """Construct the probe request payload.

        Format:
        {"type": "probe", "seq": <int>, "timestamp": <float>, "payload": "DIAG"}

        Args:
            seq: Sequence number of the probe.

        Returns:
            UTF-8 encoded JSON payload (under 512 bytes).
        """
        message = {
            "type": "probe",
            "seq": seq,
            "timestamp": time.time(),
            "payload": "DIAG",
        }
        return json.dumps(message).encode("utf-8")

    def parse_response(self, raw_data: bytes) -> Optional[Dict[str, Any]]:
        """Validate and parse incoming echo response.

        Expected response format:
        {"type": "echo", "seq": <int>, "timestamp": <float>,
         "server_timestamp": <float>, "payload": "DIAG"}

        Args:
            raw_data: Raw bytes received from the socket.

        Returns:
            Parsed dictionary or None if response is malformed.
        """
        try:
            decoded = raw_data.decode("utf-8")
            data = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
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
        """Send a single probe and wait for the matching echo response.

        Args:
            sock: The active UDP socket.
            seq: The sequence number for this probe.

        Returns:
            Dictionary detailing the probe outcome and metrics.
        """
        payload = self.build_probe_payload(seq)
        dest_addr = (self.target, self.port)

        # Use time.monotonic() for high-precision, steady elapsed time measurement.
        # time.monotonic() is not subject to system clock adjustments or NTP step changes.
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

            # Loop until we receive the response matching this sequence or timeout
            while True:
                remaining_time = self.timeout - (time.monotonic() - t_start)
                if remaining_time <= 0:
                    raise socket.timeout()

                sock.settimeout(remaining_time)
                data, addr = sock.recvfrom(BUFFER_SIZE)
                t_end = time.monotonic()

                response = self.parse_response(data)
                if response is None:
                    continue

                resp_seq = response["seq"]

                # Check if this response is a duplicate
                if resp_seq in self.seen_sequences:
                    logger.warning(
                        "Duplicate response received for sequence #%d from %s",
                        resp_seq,
                        addr,
                    )
                    continue

                # Check if response matches current probe sequence
                if resp_seq == seq:
                    rtt_ms = (t_end - t_start) * 1000.0
                    self.seen_sequences.add(resp_seq)
                    self.responses_received += 1
                    self.rtt_records.append(rtt_ms)

                    result["status"] = "success"
                    result["rtt_ms"] = round(rtt_ms, 3)
                    result["server_timestamp"] = response.get("server_timestamp")
                    print(
                        f"Probe #{seq:03d}: Reply from {addr[0]}:{addr[1]} "
                        f"bytes={len(data)} rtt={rtt_ms:.2f} ms"
                    )
                    break
                else:
                    # Received response for a different sequence (e.g., late packet)
                    logger.info(
                        "Received late or out-of-order response for sequence #%d (expected #%d)",
                        resp_seq,
                        seq,
                    )
                    self.seen_sequences.add(resp_seq)

        except socket.timeout:
            result["status"] = "timeout"
            result["error"] = "Request timed out"
            print(f"Probe #{seq:03d}: Request timed out (timeout={self.timeout:.1f}s)")

        except OSError as err:
            result["status"] = "error"
            result["error"] = str(err)
            print(f"Probe #{seq:03d}: Network error - {err}")

        return result

    def calculate_statistics(self) -> Dict[str, Any]:
        """Compute summary statistics for all sent probes.

        Returns:
            Dictionary with aggregated metrics.
        """
        # Guard against division by zero
        if self.probes_sent > 0:
            lost_probes = self.probes_sent - self.responses_received
            packet_loss_pct = (lost_probes / self.probes_sent) * 100.0
        else:
            packet_loss_pct = 0.0

        if self.rtt_records:
            min_rtt = min(self.rtt_records)
            max_rtt = max(self.rtt_records)
            avg_rtt = sum(self.rtt_records) / len(self.rtt_records)
        else:
            min_rtt = None
            max_rtt = None
            avg_rtt = None

        return {
            "target": self.target,
            "port": self.port,
            "probes_sent": self.probes_sent,
            "responses_received": self.responses_received,
            "packet_loss_percent": round(packet_loss_pct, 2),
            "rtt_min_ms": round(min_rtt, 3) if min_rtt is not None else None,
            "rtt_max_ms": round(max_rtt, 3) if max_rtt is not None else None,
            "rtt_avg_ms": round(avg_rtt, 3) if avg_rtt is not None else None,
            "individual_results": self.individual_results,
        }

    def print_summary(self, stats: Dict[str, Any]) -> None:
        """Display an ASCII summary table of the probe session.

        Args:
            stats: Summary metrics dictionary.
        """
        print("\n" + "=" * 55)
        print(f"       UDP DIAGNOSTIC PROBE SUMMARY FOR {self.target}:{self.port}")
        print("=" * 55)
        print(f" Probes Transmitted      : {stats['probes_sent']}")
        print(f" Responses Received      : {stats['responses_received']}")
        print(f" Packet Loss Percentage  : {stats['packet_loss_percent']:.2f}%")
        print("-" * 55)

        if stats["rtt_avg_ms"] is not None:
            print(f" Minimum RTT             : {stats['rtt_min_ms']:.2f} ms")
            print(f" Maximum RTT             : {stats['rtt_max_ms']:.2f} ms")
            print(f" Average RTT             : {stats['rtt_avg_ms']:.2f} ms")
        else:
            print(" Round-Trip Time (RTT)   : N/A (100% packet loss)")
        print("=" * 55 + "\n")

    def save_output(self, stats: Dict[str, Any]) -> None:
        """Write summary results to a JSON file if configured.

        Args:
            stats: Summary metrics dictionary.
        """
        if not self.output_file:
            return

        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
            print(f"Results successfully saved to '{self.output_file}'")
        except OSError as err:
            logger.error("Failed to write output to '%s': %s", self.output_file, err)

    def run(self) -> Dict[str, Any]:
        """Execute the probe diagnostic session.

        Returns:
            Dictionary containing final statistics.
        """
        sock = self.create_socket()
        print(
            f"Starting UDP diagnostic probes to {self.target}:{self.port} "
            f"({self.count} probes, timeout={self.timeout}s, interval={self.interval}s)...\n"
        )

        try:
            for seq in range(1, self.count + 1):
                result = self.send_probe(sock, seq)
                self.individual_results.append(result)

                # Delay between probes except after the last probe
                if seq < self.count:
                    time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\nProbing interrupted by user. Generating summary for sent probes...")
        finally:
            sock.close()

        stats = self.calculate_statistics()
        self.print_summary(stats)
        self.save_output(stats)
        return stats


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments for the UDP diagnostic client.

    Returns:
        argparse.Namespace containing parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Probe Client for RTT and Packet Loss Testing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target",
        type=str,
        default=DEFAULT_TARGET,
        help="Target server IP address or hostname",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Target server UDP port",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help="Number of UDP probe packets to send",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Timeout in seconds for waiting on echo response per probe",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Interval in seconds between consecutive probes",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to output file to save JSON diagnostic results",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point for the UDP diagnostic client."""
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
