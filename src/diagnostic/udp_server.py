"""UDP Diagnostic Server.

Listens for incoming UDP probe packets, inspects probe sequence numbers and
timestamps, and echoes them back with a server timestamp to enable round-trip
time (RTT) and packet loss measurements.
"""

import argparse
import json
import logging
import socket
import sys
import time
from typing import Any, Dict, Optional, Tuple

# Configure logging for diagnostics and warnings
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("UDPServer")

DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_PORT: int = 5005
BUFFER_SIZE: int = 1024


class UDPServer:
    """UDP diagnostic server for echo and RTT probing."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        """Initialize the UDP server with host and port.

        Args:
            host: IP address to bind to (e.g., '0.0.0.0' for all interfaces).
            port: Port number to bind to (e.g., 5005).
        """
        self.host: str = host
        self.port: int = port
        self.total_probes_received: int = 0
        self._sock: Optional[socket.socket] = None

    def create_socket(self) -> socket.socket:
        """Create and bind a UDP socket.

        Returns:
            A bound UDP socket.
        """
        # socket.AF_INET specifies IPv4 addressing.
        # socket.SOCK_DGRAM specifies UDP (User Datagram Protocol) - connectionless, datagram-oriented.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow address reuse if restarting server quickly
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        return sock

    def parse_probe(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Validate and parse incoming probe data.

        Expected message format:
        {"type": "probe", "seq": <int>, "timestamp": <float>, "payload": "DIAG"}

        Args:
            data: Raw received bytes.

        Returns:
            Parsed JSON dict if valid probe, otherwise None.
        """
        try:
            decoded = data.decode("utf-8")
            message = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            logger.warning("Dropped malformed packet: failed to parse JSON/UTF-8: %s", err)
            return None

        if not isinstance(message, dict):
            logger.warning("Dropped malformed packet: payload is not a JSON object")
            return None

        # Verify required keys and types
        if message.get("type") != "probe":
            logger.warning("Dropped unexpected packet type: %s", message.get("type"))
            return None

        if "seq" not in message or not isinstance(message["seq"], int):
            logger.warning("Dropped invalid probe: missing or invalid 'seq'")
            return None

        if "timestamp" not in message or not isinstance(message["timestamp"], (int, float)):
            logger.warning("Dropped invalid probe: missing or invalid 'timestamp'")
            return None

        return message

    def build_response(self, probe: Dict[str, Any]) -> bytes:
        """Build an echo response message.

        Format:
        {"type": "echo", "seq": <int>, "timestamp": <original_float>,
         "server_timestamp": <float>, "payload": "DIAG"}

        Args:
            probe: Parsed probe dictionary.

        Returns:
            UTF-8 encoded JSON bytes under 512 bytes.
        """
        response_dict = {
            "type": "echo",
            "seq": probe["seq"],
            "timestamp": probe["timestamp"],
            "server_timestamp": time.time(),
            "payload": probe.get("payload", "DIAG"),
        }
        return json.dumps(response_dict).encode("utf-8")

    def run(self) -> None:
        """Start the UDP echo server loop until interrupted."""
        self._sock = self.create_socket()
        print(f"=== UDP Diagnostic Server started on {self.host}:{self.port} ===")
        print("Press Ctrl+C to terminate.")

        try:
            while True:
                # recvfrom blocks until a datagram arrives or an error occurs.
                # In UDP, each recvfrom receives one discrete packet.
                try:
                    data, addr = self._sock.recvfrom(BUFFER_SIZE)
                except OSError as err:
                    logger.error("Socket error during receive: %s", err)
                    break

                probe = self.parse_probe(data)
                if probe is None:
                    continue

                self.total_probes_received += 1
                seq = probe["seq"]
                print(f"[Probe #{seq:04d}] Received from {addr[0]}:{addr[1]} (Total: {self.total_probes_received})")

                # Formulate echo response and send back to sender's address
                response_bytes = self.build_response(probe)
                try:
                    self._sock.sendto(response_bytes, addr)
                except OSError as err:
                    logger.warning("Failed to send echo reply to %s: %s", addr, err)

        except KeyboardInterrupt:
            print("\nShutting down server gracefully...")
        finally:
            if self._sock:
                self._sock.close()
                self._sock = None
            print(f"Server stopped. Total probes processed: {self.total_probes_received}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments for the UDP server.

    Returns:
        argparse.Namespace containing CLI arguments.
    """
    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Echo Server for Network Probing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="Host address / IP to bind the UDP server to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="UDP port to listen on",
    )
    return parser.parse_args()


def main() -> None:
    """Main CLI entry point for the UDP server."""
    args = parse_arguments()
    server = UDPServer(host=args.host, port=args.port)
    server.run()


if __name__ == "__main__":
    main()
