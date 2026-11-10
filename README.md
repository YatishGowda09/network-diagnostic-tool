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
| **UDP Diagnostic Client** | **Working** | Local / Linux | Configurable count, timeout, interval; monotonic RTT + RFC 3550 jitter calculation; duplicate handling. |
| **Path Analysis Module** | **Working** | Local / Linux | Graph representation (switches, links, hosts); BFS shortest path; DFS all paths; zero external deps. |
| **SDN Topology Client** | **Working** | Local / Linux | Standard library `urllib.request`; offline file cache, REST queries, `/topology/status` monitor. |
| **Integrated Report Generator**| **Working** | Local / Linux | Combines diagnostic stats with topology graph; exports formatted text and JSON with disclaimers. |
| **Automated Test Suite** | **Working** | Local / Linux | **67 unit & integration tests passing** (`unittest`) with 0 root or SDN dependencies required. |
| **Ryu SDN Controller** | **Working** | Ubuntu VM | L2 learning switch, LLDP topology discovery, WSGI REST API, and dynamic shortest-path reroute engine. |
| **Mininet Diamond Topology** | **Working** | Ubuntu VM | 4-switch diamond topology with 2 hosts (`h1`, `h2`), 10 Mbps TCLink, and programmatic fault injection. |
| **Dynamic SDN Failover & Rerouting** | **Working** | Local / VM | `EventLinkDelete` triggers stale flow deletion (`OFPFC_DELETE`), graph recalculation, and path failover. |
| **OpenFlow Flow Inspector** | **Working** | Local / Linux | `scripts/flow_inspector.py` inspects active OVS rules and infers data-plane forwarding routes. |
| **Multi-Condition Benchmark Suite** | **Working** | Local / Linux | `scripts/benchmark_runner.py` evaluates Baseline, Failover, Static Failure, and Stress conditions. |

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
│   ├── demo-guide.md              # Step-by-step demonstration runbook
│   └── performance-report.md      # Multi-condition benchmark evaluation report
├── src/                           # Application source code
│   ├── diagnostic/                # UDP socket diagnostic application
│   │   ├── udp_client.py          # Probe client (RTT, jitter, and packet loss)
│   │   └── udp_server.py          # Diagnostic echo server
│   ├── sdn/                       # SDN controller and topology discovery
│   │   ├── controller.py          # Ryu OpenFlow 1.3 controller with dynamic rerouting
│   │   └── topology.py            # Controller REST API client & status monitor
│   └── analysis/                  # Graph analysis and reporting
│       ├── path_analysis.py       # Graph representation & path finding (BFS/DFS)
│       └── report.py              # Integrated diagnostic + path report generator
├── topology/                      # Mininet network topologies
│   └── mininet_topology.py        # 4-switch diamond topology with link failure API
├── scripts/                       # Evaluation, benchmark, and inspection tools
│   ├── failover_demo.py           # Automated link failure & SDN rerouting demo
│   ├── flow_inspector.py          # OpenFlow flow rule inspector & path inference
│   ├── benchmark_runner.py        # Multi-condition performance benchmark suite
│   └── generate_performance_report.py # Markdown benchmark report compiler
└── tests/                         # Automated test suite (67 tests passing)
    ├── test_udp_client.py         # UDP client format, timeout, statistics, jitter tests
    ├── test_udp_server.py         # UDP server parsing and echo reply tests
    ├── test_controller_rerouting.py # Dynamic NetworkGraph path rerouting tests
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
The SDN controller and virtual network emulation require Mininet, Open vSwitch, and Ryu. An automated setup script handles all dependencies across Ubuntu 20.04, 22.04, 24.04, and 26.04+:

```bash
# Clone the repository
git clone https://github.com/YatishGowda09/network-diagnostic-tool.git
cd network-diagnostic-tool

# Run the single-step automated setup script
chmod +x install_dependencies.sh
./install_dependencies.sh
```

*(The script automatically detects your Ubuntu and Python version, installs Mininet and Open vSwitch via `apt`, creates a virtual environment, installs the compatible Ryu SDN framework, and links `ryu-manager` to `/usr/local/bin` for seamless multi-terminal execution. See [docs/demo-guide.md](docs/demo-guide.md) for detailed manual instructions).*

---

## 6. Local Testing & Verification

Without root privileges or Mininet installed, you can execute the automated test suite, standalone failover simulations, flow inspector, and benchmark runner over the loopback interface (`127.0.0.1`).

### Running the Automated Test Suite (67 Tests)
```bash
python3 -m unittest discover -s tests -v
```
*(Runs all 67 unit and loopback integration tests with 0 failures.)*

### Running the Standalone Dynamic Failover Simulation
```bash
python3 scripts/failover_demo.py --mock
```

### Running the OpenFlow Flow Table Inspector
```bash
python3 scripts/flow_inspector.py --mock
```

### Running the Multi-Condition Benchmark Suite
```bash
python3 scripts/benchmark_runner.py --count 10
python3 scripts/generate_performance_report.py
```
*(Generates `benchmark_results.json` and updates `docs/performance-report.md`.)*

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

Follow this multi-terminal sequence inside the Ubuntu virtual machine for the full end-to-end Mininet + SDN demonstration.

### Step 1: Start the Ryu Controller (Terminal 1)
```bash
ryu-manager --observe-links src/sdn/controller.py
```
*The controller listens on OpenFlow port `6633` and exposes the REST API on `http://127.0.0.1:8080/topology/*`.*

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

### Step 5: Execute Automated Link Failure & Rerouting Demo
```bash
sudo python3 scripts/failover_demo.py
```
*Automatically severs link `s1-s2`, observes dynamic SDN reroute to `s1-s3-s4`, restores link, and prints recovery metrics.*

### Step 6: Inspect Active OpenFlow Flow Tables
```bash
sudo python3 scripts/flow_inspector.py
```
*Inspects installed flow rules across `s1`-`s4` to verify physical forwarding paths.*

---

## 8. Important Engineering Disclaimers

1. **Candidate Paths vs. Forwarding Paths:**
   Graph traversal (BFS/DFS) discovers **candidate physical paths** supported by network links. The **actual forwarding path** taken by packets is determined dynamically by OpenFlow flow tables installed by the SDN controller.
2. **End-to-End Latency vs. Per-Link Delay:**
   UDP probe round-trip times measure end-to-end application-to-application transit. Without synchronized per-switch telemetry or in-band network telemetry (INT), end-to-end measurements do not reveal individual link delays.

---
