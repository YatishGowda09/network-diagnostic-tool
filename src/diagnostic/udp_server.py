"""UDP Diagnostic Server.

Listens for incoming UDP probe packets and echoes them back with a server
timestamp to enable round-trip time (RTT) and packet loss measurements.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import time
from typing import Any, Dict, Optional

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("UDPServer")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5005
BUFFER_SIZE = 1024


class UDPServer:
    """UDP diagnostic server for echo and latency probing."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.total_probes_received = 0
        self._sock: Optional[socket.socket] = None

    def create_socket(self) -> socket.socket:
        """Create and bind a UDP socket with address reuse."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        return sock

    def parse_probe(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Validate and parse incoming probe datagram."""
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as err:
            logger.warning("Dropped malformed packet: failed to parse JSON/UTF-8: %s", err)
            return None

        if not isinstance(msg, dict):
            logger.warning("Dropped malformed packet: payload is not a JSON object")
            return None

        if msg.get("type") != "probe":
            logger.warning("Dropped unexpected packet type: %s", msg.get("type"))
            return None

        if "seq" not in msg or not isinstance(msg["seq"], int):
            logger.warning("Dropped invalid probe: missing or invalid 'seq'")
            return None

        if "timestamp" not in msg or not isinstance(msg["timestamp"], (int, float)):
            logger.warning("Dropped invalid probe: missing or invalid 'timestamp'")
            return None

        return msg

    def build_response(self, probe: Dict[str, Any]) -> bytes:
        """Build echo response preserving sequence, client ts, and payload."""
        response = {
            "type": "echo",
            "seq": probe["seq"],
            "timestamp": probe["timestamp"],
            "server_timestamp": time.time(),
            "payload": probe.get("payload", "DIAG"),
        }
        return json.dumps(response).encode("utf-8")

    def run(self) -> None:
        """Run the server loop until interrupted."""
        self._sock = self.create_socket()
        print(f"=== UDP Diagnostic Server started on {self.host}:{self.port} ===")
        print("Press Ctrl+C to terminate.")

        try:
            while True:
                try:
                    data, addr = self._sock.recvfrom(BUFFER_SIZE)
                except OSError as err:
                    logger.error("Socket error during receive: %s", err)
                    break

                probe = self.parse_probe(data)
                if probe is None:
                    continue

                self.total_probes_received += 1
                print(f"[Probe #{probe['seq']:04d}] Received from {addr[0]}:{addr[1]} (Total: {self.total_probes_received})")

                try:
                    self._sock.sendto(self.build_response(probe), addr)
                except OSError as err:
                    logger.warning("Failed to send echo reply to %s: %s", addr, err)
        except KeyboardInterrupt:
            print("\nShutting down server gracefully...")
        finally:
            if self._sock:
                self._sock.close()


def main() -> None:
    """CLI entrypoint for diagnostic server."""
    parser = argparse.ArgumentParser(description="UDP Diagnostic Echo Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="IP to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    args = parser.parse_args()

    server = UDPServer(host=args.host, port=args.port)
    server.run()


if __name__ == "__main__":
    main()
