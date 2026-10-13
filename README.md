# Network Diagnostic and Path Analysis Tool

A software-defined networking (SDN) and UDP socket-based network diagnostic application that measures round-trip time (RTT), jitter, and packet loss, correlates endpoint measurements with discovered OpenFlow switch topologies, and computes candidate forwarding paths.

---

## 1. Project Summary & Objectives

The **Network Diagnostic and Path Analysis Tool** bridges application-layer diagnostic probing with SDN control-plane network visibility.

### Objectives
- **Application-Layer Probing:** Implement low-level UDP client-server socket diagnostics to measure precise round-trip times (RTT using monotonic clocks) and detect packet loss.
- **SDN Topology Discovery:** Connect OpenFlow 1.3 virtual switches to an SDN controller (Ryu) and retrieve live switch, link, and host attachments via a REST API.
- **Graph-Based Path Analysis:** Model discovered network topologies as adjacency graphs and compute candidate routing paths (BFS/DFS) between communicating end-hosts.
- **Socket–SDN Correlation:** Correlate measured network performance (RTT, loss, jitter) with candidate topology paths into unified diagnostic reports.
- **Reproducible Virtual Emulation:** Deploy and validate within a Mininet virtual network emulation environment.

---

## 2. Current Implementation Status

| Component | Status | Verified Environment | Details |
| :--- | :--- | :--- | :--- |
| **UDP Diagnostic Server** | **Working** | Local / Linux | Standard library `socket`, JSON probe parsing, echo response, malformed packet recovery. |
| **UDP Diagnostic Client** | **Working** | Local / Linux | Configurable count, timeout, interval; RTT metrics via `time.monotonic()`; duplicate handling. |
| **Path Analysis Module** | **Working** | Local / Linux | Graph representation (switches, links, hosts); BFS shortest path; DFS all paths; zero external deps. |
| **SDN Topology Client** | **Working** | Local / Linux | Standard library `urllib.request`; offline file cache & REST queries; error/timeout resilience. |
| **Integrated Report Generator**| **Working** | Local / Linux | Combines diagnostic stats with topology graph; exports formatted text and JSON with disclaimers. |
| **Automated Test Suite** | **Working** | Local / Linux | 54 unit & integration tests passing (`unittest`) with 0 root or SDN dependencies required. |
| **Ryu SDN Controller** | **Code Complete** | Ubuntu VM | L2 learning switch, LLDP topology discovery, WSGI REST API; syntax verified, awaits live Ryu run. |
| **Mininet Diamond Topology** | **Code Complete** | Ubuntu VM | 4-switch diamond topology with 2 hosts (`h1`, `h2`), 10 Mbps TCLink; awaits root Mininet run. |
| **Link Failure & Dynamic Rerouting** | *Planned* | Future Milestone | Post-Demo 1 milestone: automatic failover detection and path comparison under fault conditions. |

---

## 3. Technology Stack

- **Language:** Python 3 (standard library: `socket`, `time`, `json`, `urllib`, `collections`, `unittest`, `dataclasses`)
- **SDN Framework:** Ryu SDN Controller (OpenFlow 1.3)
- **Virtual Network Emulation:** Mininet 2.3+ with Open vSwitch (OVS)
- **Target Platform (Demo):** Ubuntu 22.04 LTS / 24.04 LTS Virtual Machine

---

## 4. Repository Structure

```
network-diagnostic-tool/
├── .gitignore                     # Git exclusion rules
├── README.md                      # Project documentation and guide
├── requirements.txt               # Python package requirements
├── docs/                          # Technical documentation
│   ├── architecture.md            # System architecture and design diagrams
│   └── demo-guide.md              # Step-by-step demonstration runbook
├── src/                           # Application source code
│   ├── diagnostic/                # UDP socket diagnostic application
│   │   ├── udp_client.py          # Probe client (RTT and packet loss)
│   │   └── udp_server.py          # Diagnostic echo server
│   ├── sdn/                       # SDN controller and topology discovery
│   │   ├── controller.py          # Ryu OpenFlow 1.3 L2 controller with REST API
│   │   └── topology.py            # Controller REST API client
│   └── analysis/                  # Graph analysis and reporting
│       ├── path_analysis.py       # Graph representation & path finding (BFS/DFS)
│       └── report.py              # Integrated diagnostic + path report generator
├── topology/                      # Mininet network topologies
│   └── mininet_topology.py        # 4-switch diamond topology with TCLink
└── tests/                         # Automated test suite (54 tests)
    ├── test_udp_client.py         # UDP client format, timeout, statistics tests
    ├── test_udp_server.py         # UDP server parsing and echo reply tests
    ├── test_path_analysis.py      # Graph path algorithms and topology parsing tests
    ├── test_topology.py           # Topology client REST handling and offline caching tests
    ├── test_report.py             # Integrated report formatting and disclaimers tests
    └── test_integration.py        # Loopback socket integration and workflow tests
```

---

## 5. Dependencies & Installation Instructions

### Core Application
The core diagnostic tool, topology client, path analysis, and report generator utilize **only Python's standard library** and require no external package installations.

### Demonstration Environment (Ubuntu VM)
The SDN controller and virtual network emulation require Mininet, Open vSwitch, and Ryu:

```bash
# Update package repositories
sudo apt update

# Install Mininet and Open vSwitch
sudo apt install -y mininet openvswitch-switch python3-pip

# Install Ryu SDN controller (inside Ubuntu virtual environment or system)
pip3 install ryu
```

> **Note on Python versions:** On systems with Python 3.12+, Ryu dependencies may require `pip install ryu --break-system-packages` or using the `os-ken` OpenFlow library. See [docs/demo-guide.md](docs/demo-guide.md) for troubleshooting.

---

## 6. Local Testing & Verification

Without root privileges or Mininet installed, you can execute the automated test suite and test the UDP diagnostic workflow over the loopback interface (`127.0.0.1`).

### Running the Automated Test Suite
```bash
python3 -m unittest discover -s tests -v
```
*(Runs all 54 unit and loopback integration tests.)*

### Running a Local UDP Diagnostic Test
In Terminal 1 (Start the diagnostic echo server):
```bash
python3 src/diagnostic/udp_server.py --host 127.0.0.1 --port 5005
```

In Terminal 2 (Run diagnostic probes):
```bash
python3 src/diagnostic/udp_client.py --target 127.0.0.1 --port 5005 --count 10 --interval 0.2 --output results.json
```

In Terminal 2 (Generate diagnostic report with sample diamond topology):
```bash
python3 src/analysis/report.py --diagnostic results.json
```

---

## 7. Complete Demonstration Instructions (Ubuntu VM)

Follow this 3-terminal sequence inside the Ubuntu virtual machine for the full end-to-end Mininet + SDN demonstration.

### Step 1: Start the Ryu Controller (Terminal 1)
```bash
ryu-manager --observe-links src/sdn/controller.py
```
*The controller will listen on OpenFlow port `6633` and expose the REST API on `http://127.0.0.1:8080/topology/*`.*

### Step 2: Start the Mininet Diamond Topology (Terminal 2)
```bash
sudo python3 topology/mininet_topology.py
```
*Mininet creates switches `s1`-`s4`, hosts `h1` (`10.0.0.1`) and `h2` (`10.0.0.2`), and connects to Ryu.*

### Step 3: Test Baseline Connectivity & Start Services (Mininet CLI)
```bash
mininet> pingall
mininet> h2 python3 src/diagnostic/udp_server.py --host 10.0.0.2 --port 5005 &
mininet> h1 python3 src/diagnostic/udp_client.py --target 10.0.0.2 --port 5005 --count 20 --output /tmp/demo_diag.json
```

### Step 4: Extract Topology & Generate Integrated Report (Terminal 3)
```bash
# Query the live SDN controller topology
python3 src/sdn/topology.py --controller http://127.0.0.1:8080 --save /tmp/demo_topo.json

# Generate the integrated path analysis report
python3 src/analysis/report.py --diagnostic /tmp/demo_diag.json --topology /tmp/demo_topo.json --source 10.0.0.1 --dest 10.0.0.2
```

---

## 8. Important Engineering Disclaimers

1. **Candidate Paths vs. Forwarding Paths:**
   Graph traversal (BFS/DFS) discovers **candidate physical paths** supported by network links. The **actual forwarding path** taken by packets is determined dynamically by OpenFlow flow tables installed by the SDN controller.
2. **End-to-End Latency vs. Per-Link Delay:**
   UDP probe round-trip times measure end-to-end application-to-application transit. Without synchronized per-switch telemetry or in-band network telemetry (INT), end-to-end measurements do not reveal individual link delays.

---

## 9. Known Limitations & Next Steps

### Limitations
- Topology host discovery in Ryu requires initial packet traffic (ARP/ping) before hosts appear in the controller host database.
- Dynamic link failover and automated flow rerouting are not yet implemented for Demo 1.

### Next Steps for Team
1. **VM Integration Test:** Boot the Ubuntu VM and perform a live run of the 3-terminal demonstration sequence.
2. **Flow Inspection Tooling:** Add `ovs-ofctl dump-flows` validation to confirm which candidate path is actively forwarding packets.
3. **Link Failure Injection:** Implement automated link down/up testing (`link s1 s2 down`) to evaluate packet loss during topology changes.
