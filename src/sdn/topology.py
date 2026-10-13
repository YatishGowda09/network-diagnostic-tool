"""SDN Topology Client.

This module provides a client interface to query topology data from the
Ryu SDN Controller's REST API using Python's standard library (`urllib.request`).
Supports offline file caching, offline topology loading, and standalone CLI usage.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TopologyClient:
    """Client for interacting with the SDN Controller's Topology REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 5.0) -> None:
        """Initialize TopologyClient.

        Args:
            base_url: Base URL of controller REST service (e.g., http://127.0.0.1:8080)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _make_request(self, endpoint: str) -> Optional[Any]:
        """Send HTTP GET request to controller endpoint and parse JSON.

        Args:
            endpoint: Relative path endpoint (e.g. '/topology/switches')

        Returns:
            Parsed JSON object (dict/list) or None if request fails.
        """
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SDN-TopologyClient/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status = response.status
                if status != 200:
                    logger.warning("HTTP %d received from %s", status, url)
                    return None
                data_bytes = response.read()
                try:
                    return json.loads(data_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    logger.error("Malformed JSON response from %s: %s", url, err)
                    return None
        except urllib.error.HTTPError as err:
            logger.error("HTTP error querying %s: %d %s", url, err.code, err.reason)
            return None
        except urllib.error.URLError as err:
            logger.error("Network error connecting to %s: %s", url, err.reason)
            return None
        except TimeoutError:
            logger.error("Connection timed out querying %s (timeout=%.1fs)", url, self.timeout)
            return None
        except Exception as err:
            logger.error("Unexpected error querying %s: %s", url, err)
            return None

    def get_switches(self) -> List[Dict[str, Any]]:
        """Retrieve list of connected switches from controller."""
        data = self._make_request("/topology/switches")
        if isinstance(data, list):
            return data
        return []

    def get_links(self) -> List[Dict[str, Any]]:
        """Retrieve list of inter-switch links from controller."""
        data = self._make_request("/topology/links")
        if isinstance(data, list):
            return data
        return []

    def get_hosts(self) -> List[Dict[str, Any]]:
        """Retrieve list of discovered hosts from controller."""
        data = self._make_request("/topology/hosts")
        if isinstance(data, list):
            return data
        return []

    def get_full_topology(self) -> Dict[str, Any]:
        """Retrieve aggregated topology view (switches, links, hosts)."""
        data = self._make_request("/topology/full")
        if isinstance(data, dict):
            return {
                "switches": data.get("switches", []),
                "links": data.get("links", []),
                "hosts": data.get("hosts", []),
            }

        # Fallback to querying endpoints individually if /topology/full is missing
        logger.info("Fetching individual topology components as fallback...")
        return {
            "switches": self.get_switches(),
            "links": self.get_links(),
            "hosts": self.get_hosts(),
        }

    def save_topology(self, filepath: str, topology_data: Optional[Dict[str, Any]] = None) -> bool:
        """Save topology data to a JSON file.

        Args:
            filepath: Target file path
            topology_data: Optional topology dict to save; fetches from controller if None.

        Returns:
            True if saved successfully, False otherwise.
        """
        if topology_data is None:
            topology_data = self.get_full_topology()

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(topology_data, f, indent=2)
            logger.info("Saved topology data to %s", filepath)
            return True
        except (OSError, IOError) as err:
            logger.error("Failed to save topology to %s: %s", filepath, err)
            return False

    @staticmethod
    def load_topology(filepath: str) -> Dict[str, Any]:
        """Load topology data from an offline JSON file.

        Args:
            filepath: Path to the JSON topology file.

        Returns:
            Dictionary with switches, links, and hosts. Empty dict if load fails.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.error("Topology file %s did not contain a JSON object", filepath)
                return {"switches": [], "links": [], "hosts": []}
            return {
                "switches": data.get("switches", []),
                "links": data.get("links", []),
                "hosts": data.get("hosts", []),
            }
        except (OSError, IOError, json.JSONDecodeError) as err:
            logger.error("Failed to load topology from %s: %s", filepath, err)
            return {"switches": [], "links": [], "hosts": []}


def main() -> None:
    """CLI entrypoint for testing topology client."""
    parser = argparse.ArgumentParser(
        description="SDN Topology Client - Query and inspect controller topology"
    )
    parser.add_argument(
        "--controller",
        default="http://127.0.0.1:8080",
        help="Controller REST API base URL (default: http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP request timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="File path to save the retrieved topology JSON",
    )
    parser.add_argument(
        "--load",
        type=str,
        default=None,
        help="File path to load an offline topology JSON instead of querying controller",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")

    client = TopologyClient(base_url=args.controller, timeout=args.timeout)

    if args.load:
        print(f"Loading topology from offline file: {args.load}")
        topology = client.load_topology(args.load)
    else:
        print(f"Connecting to SDN controller at {args.controller}...")
        topology = client.get_full_topology()

    print("\n--- Network Topology Summary ---")
    switches = topology.get("switches", [])
    links = topology.get("links", [])
    hosts = topology.get("hosts", [])

    print(f"Switches: {len(switches)}")
    for sw in switches:
        ports = sw.get("ports", [])
        port_list = ", ".join(f"p{p.get('port_no')}" for p in ports)
        print(f"  Switch {sw.get('dpid')}: Ports [{port_list}]")

    print(f"\nLinks: {len(links)}")
    for link in links:
        print(
            f"  {link.get('src_dpid')}:{link.get('src_port')} <---> "
            f"{link.get('dst_dpid')}:{link.get('dst_port')}"
        )

    print(f"\nHosts: {len(hosts)}")
    for host in hosts:
        print(
            f"  MAC: {host.get('mac')} | IP: {host.get('ipv4')} | "
            f"Attached: {host.get('dpid')}:{host.get('port')}"
        )

    if args.save:
        client.save_topology(args.save, topology)
        print(f"\nTopology successfully saved to {args.save}")


if __name__ == "__main__":
    main()
