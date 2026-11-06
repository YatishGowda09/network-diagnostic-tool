"""SDN Topology Client.

Provides a client interface to query topology data from the Ryu SDN
Controller's REST API using Python's standard library (urllib.request).
"""

from __future__ import annotations

import argparse
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TopologyClient:
    """Client for interacting with the Ryu SDN Controller Topology REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _make_request(self, endpoint: str) -> Optional[Any]:
        """Send HTTP GET request to controller endpoint and parse JSON."""
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SDN-TopologyClient/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    logger.warning("HTTP %d received from %s", response.status, url)
                    return None
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, Exception) as err:
            logger.error("Error querying %s: %s", url, err)
            return None

    def get_switches(self) -> List[Dict[str, Any]]:
        """Retrieve list of connected switches."""
        data = self._make_request("/topology/switches")
        return data if isinstance(data, list) else []

    def get_links(self) -> List[Dict[str, Any]]:
        """Retrieve list of inter-switch links."""
        data = self._make_request("/topology/links")
        return data if isinstance(data, list) else []

    def get_hosts(self) -> List[Dict[str, Any]]:
        """Retrieve list of discovered hosts."""
        data = self._make_request("/topology/hosts")
        return data if isinstance(data, list) else []

    def get_status(self) -> Dict[str, Any]:
        """Retrieve dynamic SDN operational status and active paths."""
        data = self._make_request("/topology/status")
        if isinstance(data, dict):
            return data
        return {
            "switches_online": 0,
            "links_active": 0,
            "hosts_tracked": 0,
            "active_paths": {},
            "recent_events": [],
        }

    def get_full_topology(self) -> Dict[str, Any]:
        """Retrieve aggregated topology view (switches, links, hosts)."""
        data = self._make_request("/topology/full")
        if isinstance(data, dict):
            return {
                "switches": data.get("switches", []),
                "links": data.get("links", []),
                "hosts": data.get("hosts", []),
            }
        return {
            "switches": self.get_switches(),
            "links": self.get_links(),
            "hosts": self.get_hosts(),
        }

    def save_topology(self, filepath: str, topology_data: Optional[Dict[str, Any]] = None) -> bool:
        """Save topology data to a JSON file."""
        data = topology_data if topology_data is not None else self.get_full_topology()
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("Saved topology data to %s", filepath)
            return True
        except (OSError, IOError) as err:
            logger.error("Failed to save topology to %s: %s", filepath, err)
            return False

    @staticmethod
    def load_topology(filepath: str) -> Dict[str, Any]:
        """Load topology data from an offline JSON file."""
        fallback = {"switches": [], "links": [], "hosts": []}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return fallback
            return {
                "switches": data.get("switches", []),
                "links": data.get("links", []),
                "hosts": data.get("hosts", []),
            }
        except (OSError, IOError, json.JSONDecodeError):
            return fallback


def main() -> None:
    """CLI entrypoint for querying topology client."""
    parser = argparse.ArgumentParser(description="SDN Topology Client")
    parser.add_argument("--controller", default="http://127.0.0.1:8080", help="Controller REST API URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout (s)")
    parser.add_argument("--save", help="Path to save retrieved JSON topology")
    parser.add_argument("--load", help="Load offline JSON file instead of querying controller")
    parser.add_argument("--status", action="store_true", help="Query dynamic SDN status")
    args = parser.parse_args()

    client = TopologyClient(base_url=args.controller, timeout=args.timeout)
    topo = client.load_topology(args.load) if args.load else client.get_full_topology()

    print(f"\n--- Topology: {len(topo.get('switches', []))} switches, {len(topo.get('links', []))} links, {len(topo.get('hosts', []))} hosts ---")
    if args.status:
        st = client.get_status()
        print(f"SDN Status: {st.get('switches_online')} switches online, active paths: {len(st.get('active_paths', {}))}")
    if args.save:
        client.save_topology(args.save, topo)


if __name__ == "__main__":
    main()
