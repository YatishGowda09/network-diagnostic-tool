#!/usr/bin/env bash
# =============================================================================
# Network Diagnostic & Path Analysis Tool - Demo Dependency Installer
# Automates environment preparation for Ubuntu (20.04, 22.04, 24.04, 26.04+)
# =============================================================================

set -e

# Detect text colors
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}==================================================================${RESET}"
echo -e "${BOLD}${CYAN}   Network Diagnostic & Path Analysis Tool - Demo Setup Script   ${RESET}"
echo -e "${BOLD}${CYAN}==================================================================${RESET}"

# Determine directory paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/.venv"

# Detect real user if run via sudo
if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
    REAL_GROUP="$(id -gn "$SUDO_USER")"
else
    REAL_USER="$(whoami)"
    REAL_GROUP="$(id -gn)"
fi

echo -e "\n${BOLD}[1/5] Checking System Environment...${RESET}"

# Verify Linux OS
if [ "$(uname -s)" != "Linux" ]; then
    echo -e "${RED}[ERROR] This setup script is intended for Linux (Ubuntu/Debian).${RESET}"
    exit 1
fi

# Check for apt-get
if ! command -v apt-get &>/dev/null; then
    echo -e "${RED}[ERROR] apt-get not found. Please run on an Ubuntu/Debian-based system.${RESET}"
    exit 1
fi

# Detect sudo privileges
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo &>/dev/null; then
        SUDO="sudo"
    else
        echo -e "${RED}[ERROR] Root privileges required to install system packages. Please install sudo or run as root.${RESET}"
        exit 1
    fi
fi

echo -e "${GREEN}[✓] System: Linux with apt package manager.${RESET}"

echo -e "\n${BOLD}[2/5] Installing System Packages (Mininet, OVS, build tools)...${RESET}"
$SUDO apt-get update -y
$SUDO apt-get install -y \
    mininet \
    openvswitch-switch \
    python3 \
    python3-pip \
    python3-venv \
    git \
    gcc \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev

# Ensure Open vSwitch service is running
echo -e "${CYAN}[*] Starting Open vSwitch daemon...${RESET}"
$SUDO systemctl start openvswitch-switch 2>/dev/null || $SUDO service openvswitch-switch start 2>/dev/null || true
echo -e "${GREEN}[✓] System packages and services ready.${RESET}"

echo -e "\n${BOLD}[3/5] Setting Up Python Virtual Environment...${RESET}"
# Detect system python version
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
echo -e "${CYAN}[*] Detected Python ${PY_MAJOR}.${PY_MINOR}${RESET}"

# Create virtual environment with --system-site-packages so Mininet's apt package is visible
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${CYAN}[*] Creating virtual environment at $VENV_DIR ...${RESET}"
    python3 -m venv --system-site-packages "$VENV_DIR"
else
    echo -e "${CYAN}[*] Existing virtual environment found at $VENV_DIR.${RESET}"
fi

# Upgrade pip, setuptools, and wheel in virtual environment
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel

echo -e "\n${BOLD}[4/5] Installing Ryu SDN Controller Framework...${RESET}"

INSTALL_SUCCESS=false

# If Python 3.12+, standard upstream ryu fails due to removed distutils/imp.
# Attempt installing the Python 3.12-compatible Ryu fork first.
if [ "$PY_MINOR" -ge 12 ]; then
    echo -e "${YELLOW}[!] Python 3.12+ detected. Installing Python 3.12-compatible Ryu build...${RESET}"
    if "$VENV_DIR/bin/pip" install git+https://github.com/olibrius/ryu4312.git; then
        INSTALL_SUCCESS=true
        echo -e "${GREEN}[✓] Successfully installed Python 3.12 Ryu fork (olibrius/ryu4312).${RESET}"
    else
        echo -e "${YELLOW}[!] Git fork install failed. Falling back to OpenStack os-ken...${RESET}"
        if "$VENV_DIR/bin/pip" install os-ken; then
            INSTALL_SUCCESS=true
            echo -e "${GREEN}[✓] Successfully installed os-ken fallback.${RESET}"
        fi
    fi
else
    echo -e "${CYAN}[*] Installing Ryu package for Python ${PY_MAJOR}.${PY_MINOR}...${RESET}"
    if "$VENV_DIR/bin/pip" install ryu; then
        INSTALL_SUCCESS=true
        echo -e "${GREEN}[✓] Successfully installed official ryu package.${RESET}"
    else
        echo -e "${YELLOW}[!] Standard install failed. Trying patched Ryu fork...${RESET}"
        if "$VENV_DIR/bin/pip" install git+https://github.com/olibrius/ryu4312.git; then
            INSTALL_SUCCESS=true
            echo -e "${GREEN}[✓] Successfully installed patched Ryu fork.${RESET}"
        fi
    fi
fi

if [ "$INSTALL_SUCCESS" = false ]; then
    echo -e "${RED}[ERROR] Failed to install Ryu controller. Please check internet connectivity or git access.${RESET}"
    exit 1
fi

echo -e "\n${BOLD}[5/5] Configuring Executable Links & Permissions...${RESET}"

# Create convenient symlink in /usr/local/bin so ryu-manager is available globally across all terminals
if [ -f "$VENV_DIR/bin/ryu-manager" ]; then
    $SUDO ln -sf "$VENV_DIR/bin/ryu-manager" /usr/local/bin/ryu-manager
    echo -e "${GREEN}[✓] Symlinked /usr/local/bin/ryu-manager -> $VENV_DIR/bin/ryu-manager${RESET}"
elif [ -f "$VENV_DIR/bin/os-ken-manager" ]; then
    $SUDO ln -sf "$VENV_DIR/bin/os-ken-manager" /usr/local/bin/ryu-manager
    $SUDO ln -sf "$VENV_DIR/bin/os-ken-manager" /usr/local/bin/os-ken-manager
    echo -e "${GREEN}[✓] Symlinked /usr/local/bin/ryu-manager -> $VENV_DIR/bin/os-ken-manager${RESET}"
fi

# Ensure correct file ownership for virtual environment
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    $SUDO chown -R "$REAL_USER:$REAL_GROUP" "$VENV_DIR" 2>/dev/null || true
fi

# Verify Ryu / os-ken execution
MANAGER_VERSION=""
if command -v ryu-manager &>/dev/null; then
    MANAGER_VERSION="$(ryu-manager --version 2>&1 || true)"
fi

echo -e "\n${BOLD}${GREEN}==================================================================${RESET}"
echo -e "${BOLD}${GREEN}   Environment Setup Complete!                                    ${RESET}"
echo -e "${BOLD}${GREEN}==================================================================${RESET}"
echo -e "Ryu Version : ${MANAGER_VERSION:-Installed in $VENV_DIR}"
echo -e "Mininet     : $(mn --version 2>/dev/null || echo 'Installed')"
echo -e "OVS Switch  : $(ovs-vsctl --version 2>/dev/null | head -n 1 || echo 'Installed')"
echo -e "Virtualenv  : $VENV_DIR"

echo -e "\n${BOLD}${CYAN}How to Run the Demo (Open 3 Separate Terminals):${RESET}\n"

echo -e "${BOLD}Terminal 1 (Ryu SDN Controller):${RESET}"
echo -e "  cd $PROJECT_DIR"
echo -e "  ryu-manager src/sdn/controller.py --observe-links\n"

echo -e "${BOLD}Terminal 2 (Mininet Diamond Topology):${RESET}"
echo -e "  cd $PROJECT_DIR"
echo -e "  sudo python3 topology/mininet_topology.py\n"

echo -e "${BOLD}Terminal 3 (Topology Client & Diagnostics):${RESET}"
echo -e "  cd $PROJECT_DIR"
echo -e "  python3 src/diagnostic/topology_client.py --save demo_topo.json"
echo -e "  python3 src/analysis/path_analyzer.py --file demo_topo.json --src s1 --dst s4"
echo -e "  python3 scripts/failover_demo.py --mock\n"

echo -e "${CYAN}Tip: You can also activate the virtual environment anytime via:${RESET}"
echo -e "  source $VENV_DIR/bin/activate\n"
