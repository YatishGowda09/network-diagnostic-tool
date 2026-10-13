# Network Diagnostic and Path Analysis Tool: Demonstration Guide & Runbook

This document is the **primary operational runbook** for demonstrating the Network Diagnostic and Path Analysis Tool. Follow the steps sequentially to prepare the environment, spin up the SDN control plane, instantiate the emulated network topology, run active UDP diagnostic probes, extract topology state, and generate an integrated correlation report.

> [!NOTE]
> **Environment Distinctions:**
> - **Ubuntu VM:** Full end-to-end SDN demonstration environment with Mininet, Open vSwitch, and the Ryu controller.
> - **Local Host:** Standalone local testing without Mininet (loopback UDP diagnostics, unit tests, and offline graph analysis).

---

## 1. Prerequisites & Environment Setup (Ubuntu VM)

### System Requirements
- Ubuntu 20.04 LTS or Ubuntu 22.04 LTS (recommended inside VirtualBox, VMware, or cloud instance)
- Python 3.8+
- Root / `sudo` administrative privileges

### Installation Commands

Run the following commands in an Ubuntu terminal:

```bash
# Update package repositories
sudo apt update

# Install Mininet, Open vSwitch, and core tools
sudo apt install -y mininet openvswitch-switch python3-pip git

# Install Ryu SDN Framework
pip3 install ryu
```

### Clone Repository

Clone the project repository to your workspace:

```bash
git clone git@github.com:YatishGowda09/network-diagnostic-tool.git
cd network-diagnostic-tool
```

---

## 2. Step-by-Step Demonstration Sequence

To conduct the demo cleanly, open **three separate terminal windows** on the Ubuntu VM.

```
+-----------------------------------------------------------+
| Terminal 1 (Ubuntu VM)                                    |
| Role: Ryu SDN Controller App                              |
| Privilege: User / Sudo                                    |
+-----------------------------------------------------------+
| Terminal 2 (Ubuntu VM)                                    |
| Role: Mininet Network Topology & Host Commands            |
| Privilege: Root (sudo)                                    |
+-----------------------------------------------------------+
| Terminal 3 (Ubuntu VM)                                    |
| Role: Topology Extraction & Integrated Reporting          |
| Privilege: Standard User                                  |
+-----------------------------------------------------------+
```

---

### Step 1: Start Ryu SDN Controller

In **Terminal 1**, run the custom Ryu controller application with LLDP link discovery enabled:

```bash
ryu-manager src/sdn/controller.py --observe-links
```

**Expected Behavior:**
- The controller initializes and logs that WSGI server listening on `http://0.0.0.0:8080` (or `127.0.0.1:8080`).
- Wait until the prompt indicates that the OpenFlow 1.3 switch manager is listening for switch connections on port `6653` or `6633`.

---

### Step 2: Start Mininet Diamond Topology

In **Terminal 2**, start the diamond topology script using `sudo`:

```bash
sudo python3 topology/mininet_topology.py
```

**Expected Behavior:**
- Mininet creates 4 Open vSwitch instances (`s1`, `s2`, `s3`, `s4`) and 2 hosts (`h1` at `10.0.0.1`, `h2` at `10.0.0.2`).
- Switches connect to the remote Ryu controller running on `127.0.0.1:6653` / `6633`.
- Terminal 1 logs switch join events (`datapath joined: dpid=1, 2, 3, 4`).
- Mininet opens the interactive CLI prompt: `mininet>`.

---

### Step 3: Verify Data-Plane Connectivity

Inside the **Mininet CLI** in **Terminal 2**, test basic end-to-end connectivity:

```bash
mininet> pingall
```

Then send standard ICMP pings between `h1` and `h2`:

```bash
mininet> h1 ping -c 3 h2
```

**Expected Behavior:**
- The first packet may trigger an ARP / OpenFlow `Packet-In` event to Ryu as MAC addresses are learned.
- Subsequent pings succeed with 0% packet loss.

---

### Step 4: Start UDP Echo Server on Host h2

Inside the **Mininet CLI** in **Terminal 2**, launch the diagnostic echo server in the background on `h2`:

```bash
mininet> h2 python3 src/diagnostic/udp_server.py --host 10.0.0.2 --port 5005 &
```

**Expected Behavior:**
- The server binds to `10.0.0.2:5005` in `h2`'s network namespace and listens for probe packets.

---

### Step 5: Execute UDP Diagnostic Client on Host h1

Inside the **Mininet CLI** in **Terminal 2**, run the probe client on `h1` sending 20 diagnostic packets:

```bash
mininet> h1 python3 src/diagnostic/udp_client.py --target 10.0.0.2 --port 5005 --count 20 --output results.json
```

**Expected Behavior:**
- Client outputs sequential probe logs showing sequence numbers (`seq=1, 2, ... 20`), round-trip times for each echo received, and final statistics (packets transmitted, received, loss percentage, and RTT min/avg/max/jitter).
- Results are saved to `results.json`.

---

### Step 6: Query SDN Topology via REST API

In **Terminal 3** (standard user prompt), extract the discovered network graph from the controller:

```bash
python3 src/sdn/topology.py --controller http://127.0.0.1:8080 --output topology.json
```

**Expected Behavior:**
- The client connects to the controller REST endpoints (`/topology/switches`, `/topology/links`, `/topology/hosts`).
- It prints a summary of switches and links discovered via LLDP and saves the JSON representation to `topology.json`.

---

### Step 7: Generate Integrated Correlation Report

In **Terminal 3**, combine the diagnostic measurements and topology graph into a final analysis report:

```bash
python3 src/analysis/report.py --diagnostic results.json --topology topology.json --source 10.0.0.1 --dest 10.0.0.2
```

**Expected Behavior:**
- Displays an integrated summary:
  - Source (`10.0.0.1`) and Destination (`10.0.0.2`).
  - Active Data-Plane Metrics: Total packets sent, received, loss percentage, RTT min, max, average, and jitter.
  - Control-Plane Graph Paths: Discovered switches, shortest hop path (BFS), and all loop-free candidate paths (`s1 -> s2 -> s4` and `s1 -> s3 -> s4`).

---

## 3. Quick Local Test (Host / No Mininet)

For rapid development and verification of socket code without requiring Mininet or Ryu, execute the loopback test on your local machine:

### Terminal 1: Start Local Server
```bash
python3 src/diagnostic/udp_server.py --host 127.0.0.1 --port 5005
```

### Terminal 2: Run Local Client
```bash
python3 src/diagnostic/udp_client.py --target 127.0.0.1 --port 5005 --count 10
```

**Expected Behavior:**
- The client sends 10 probes over `127.0.0.1`, receives all 10 responses, reports 0% loss, and displays sub-millisecond local loopback RTT stats.

---

## 4. Troubleshooting & Common Pitfalls

| Symptom / Issue | Probable Cause | Corrective Action |
| :--- | :--- | :--- |
| **`Connection refused` on REST API** | Ryu controller is not running or WSGI server crashed | Verify Terminal 1 is active. Ensure port `8080` is not blocked by another process (`sudo lsof -i :8080`). |
| **`pingall` reports 100% dropped packets** | Switches failed to establish OpenFlow handshake | Check OpenFlow port. If Ryu listens on `6653`, ensure Mininet connects to `6653`. Ensure `--observe-links` is supplied. |
| **`Address already in use` (Port 5005 or 6653)** | Lingering server or old Ryu instance | Kill existing process: `sudo kill -9 $(pgrep -f udp_server)` or `sudo kill -9 $(pgrep -f ryu-manager)`. |
| **Mininet freezes or reports clean-up errors** | Previous Mininet session was killed improperly | Run Mininet clean command: `sudo mn -c`. |
| **Topology discovery shows 0 links** | LLDP frames not sent or dropped | Ensure `--observe-links` is passed to `ryu-manager`. Wait 5-10 seconds for initial LLDP exchange across all switch ports. |

---

## 5. Teardown and Cleanup Commands

After completing the demonstration, shut down processes cleanly:

1. **Inside Mininet CLI (Terminal 2):**
   ```bash
   mininet> exit
   ```
2. **Clean Mininet and Open vSwitch residual states (Terminal 2):**
   ```bash
   sudo mn -c
   ```
3. **Stop Ryu Controller (Terminal 1):**
   Press `Ctrl+C` in Terminal 1.
4. **Kill any background UDP servers if left running:**
   ```bash
   sudo pkill -f udp_server.py
   ```
