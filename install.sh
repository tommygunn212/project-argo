#!/bin/bash
#
# ARGO One-Click Installer for macOS
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tommygunn212/project-argo/audio-reset-phase0/install.sh | bash
#

set -e

# ============================================================================
# CONFIGURATION
# ============================================================================
ARGO_VERSION="1.6.24"
REPO_URL="https://github.com/tommygunn212/project-argo"
REPO_BRANCH="audio-reset-phase0"
INSTALL_DIR="$HOME/argo"
PYTHON_MIN_VERSION="3.10"
OLLAMA_MODEL="qwen2.5:3b"

# ============================================================================
# COLORS
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# ============================================================================
# HELPERS
# ============================================================================
step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok() { echo -e "  ${GREEN}✓ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err() { echo -e "  ${RED}✗ $1${NC}"; }
info() { echo -e "    ${GRAY}$1${NC}"; }

command_exists() { command -v "$1" &> /dev/null; }

get_python_version() {
    if command_exists python3; then
        python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1
    else
        echo ""
    fi
}

version_gte() {
    # Returns 0 if $1 >= $2
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# ============================================================================
# BANNER
# ============================================================================
clear
echo ""
echo -e "${CYAN}  █████╗ ██████╗  ██████╗  ██████╗ ${NC}"
echo -e "${CYAN} ██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗${NC}"
echo -e "${CYAN} ███████║██████╔╝██║  ███╗██║   ██║${NC}"
echo -e "${CYAN} ██╔══██║██╔══██╗██║   ██║██║   ██║${NC}"
echo -e "${CYAN} ██║  ██║██║  ██║╚██████╔╝╚██████╔╝${NC}"
echo -e "${CYAN} ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ${NC}"
echo ""
echo -e "${GRAY}  One-Click Installer v${ARGO_VERSION} (macOS)${NC}"
echo -e "${GRAY}  ─────────────────────────────────────${NC}"
echo ""

# ============================================================================
# STEP 1: CHECK HOMEBREW
# ============================================================================
step "Checking Homebrew..."

if command_exists brew; then
    ok "Homebrew found"
else
    warn "Homebrew not found"
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add to PATH for this session
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    
    if command_exists brew; then
        ok "Homebrew installed"
    else
        err "Homebrew installation failed"
        exit 1
    fi
fi

# ============================================================================
# STEP 2: CHECK PYTHON
# ============================================================================
step "Checking Python installation..."

PYTHON_VERSION=$(get_python_version)
if [[ -n "$PYTHON_VERSION" ]] && version_gte "$PYTHON_VERSION" "$PYTHON_MIN_VERSION"; then
    ok "Python $PYTHON_VERSION found"
else
    warn "Python $PYTHON_MIN_VERSION+ not found"
    info "Installing Python via Homebrew..."
    brew install python@3.11
    
    PYTHON_VERSION=$(get_python_version)
    if [[ -n "$PYTHON_VERSION" ]]; then
        ok "Python $PYTHON_VERSION installed"
    else
        err "Python installation failed"
        exit 1
    fi
fi

# ============================================================================
# STEP 3: CHECK OLLAMA
# ============================================================================
step "Checking Ollama installation..."

if command_exists ollama; then
    ok "Ollama found"
else
    warn "Ollama not found"
    info "Installing Ollama via Homebrew..."
    brew install ollama
    
    if command_exists ollama; then
        ok "Ollama installed"
    else
        err "Ollama installation failed"
        info "Please install manually from https://ollama.com/download"
        exit 1
    fi
fi

# ============================================================================
# STEP 4: CHECK PORTAUDIO (for sounddevice)
# ============================================================================
step "Checking PortAudio (audio library)..."

if brew list portaudio &>/dev/null; then
    ok "PortAudio found"
else
    info "Installing PortAudio..."
    brew install portaudio
    ok "PortAudio installed"
fi

# ============================================================================
# STEP 5: DOWNLOAD ARGO
# ============================================================================
step "Downloading ARGO source code..."

if [[ -d "$INSTALL_DIR" ]]; then
    info "Existing installation found at $INSTALL_DIR"
    read -p "    Overwrite? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        info "Keeping existing installation"
    fi
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
    if command_exists git; then
        info "Cloning repository..."
        git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1 | while read line; do info "$line"; done
        ok "Repository cloned"
    else
        info "Git not found, downloading ZIP..."
        ZIP_URL="$REPO_URL/archive/refs/heads/$REPO_BRANCH.zip"
        ZIP_PATH="/tmp/argo-source.zip"
        
        curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
        unzip -q "$ZIP_PATH" -d /tmp
        mv "/tmp/project-argo-$REPO_BRANCH" "$INSTALL_DIR"
        rm "$ZIP_PATH"
        ok "Source code downloaded"
    fi
fi

# ============================================================================
# STEP 6: CREATE VIRTUAL ENVIRONMENT
# ============================================================================
step "Creating Python virtual environment..."

cd "$INSTALL_DIR"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# ============================================================================
# STEP 7: INSTALL DEPENDENCIES
# ============================================================================
step "Installing Python dependencies (this may take a few minutes)..."

cd "$INSTALL_DIR"
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Dependencies installed"

# ============================================================================
# STEP 8: PULL OLLAMA MODEL
# ============================================================================
step "Pulling LLM model ($OLLAMA_MODEL)..."

# Start Ollama if not running
if ! pgrep -x "ollama" > /dev/null; then
    info "Starting Ollama service..."
    ollama serve &>/dev/null &
    sleep 3
fi

info "Downloading model (this may take 5-10 minutes on first run)..."
ollama pull "$OLLAMA_MODEL" 2>&1 | while read line; do info "$line"; done
ok "Model ready"

# ============================================================================
# STEP 9: CREATE CONFIG FILE
# ============================================================================
step "Creating configuration..."

CONFIG_PATH="$INSTALL_DIR/config.json"
if [[ ! -f "$CONFIG_PATH" ]]; then
    cat > "$CONFIG_PATH" << 'EOF'
{
  "audio": {
    "input_device_index": null,
    "output_device_index": null,
    "always_listen": true
  },
  "session": {
    "turn_limit": 6
  },
  "personality": {
    "default": "tommy_gunn"
  }
}
EOF
    ok "Default config created"
    warn "You may need to set audio device indices in config.json"
else
    ok "Config file already exists"
fi

# ============================================================================
# STEP 10: CREATE LAUNCHER SCRIPT
# ============================================================================
step "Creating launcher script..."

LAUNCHER_PATH="$INSTALL_DIR/start_argo.sh"
cat > "$LAUNCHER_PATH" << 'EOF'
#!/bin/bash
# ARGO Launcher

cd "$(dirname "$0")"

# Start Ollama if not running
if ! pgrep -x "ollama" > /dev/null; then
    echo "Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 2
fi

# Activate venv and run
echo "Starting ARGO..."
source .venv/bin/activate
python main.py
EOF

chmod +x "$LAUNCHER_PATH"
ok "Launcher script created"

# ============================================================================
# STEP 11: CREATE ALIAS (optional)
# ============================================================================
step "Setting up shell alias..."

SHELL_RC=""
if [[ -f "$HOME/.zshrc" ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [[ -n "$SHELL_RC" ]]; then
    if ! grep -q "alias argo=" "$SHELL_RC"; then
        echo "" >> "$SHELL_RC"
        echo "# ARGO Voice Assistant" >> "$SHELL_RC"
        echo "alias argo='$INSTALL_DIR/start_argo.sh'" >> "$SHELL_RC"
        ok "Added 'argo' alias to $SHELL_RC"
        info "Run 'source $SHELL_RC' or open a new terminal to use it"
    else
        ok "Alias already exists"
    fi
else
    warn "Could not find shell config file"
    info "Add this to your shell config: alias argo='$INSTALL_DIR/start_argo.sh'"
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${GREEN}  ═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ ARGO Installation Complete!${NC}"
echo -e "${GREEN}  ═══════════════════════════════════════════${NC}"
echo ""
echo -e "${GRAY}  Installation path: $INSTALL_DIR${NC}"
echo ""
echo -e "  To start ARGO:"
echo -e "${GRAY}    • Run: $INSTALL_DIR/start_argo.sh${NC}"
echo -e "${GRAY}    • Or (after restarting terminal): argo${NC}"
echo ""
echo -e "${YELLOW}  First-time setup:${NC}"
echo -e "${GRAY}    1. Open $INSTALL_DIR/config.json${NC}"
echo -e "${GRAY}    2. Set your audio device indices${NC}"
echo ""
echo -e "${CYAN}  UI Dashboard: http://localhost:8000${NC}"
echo ""

# Offer to run audio device check
read -p "Would you like to see your audio devices now? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    cd "$INSTALL_DIR"
    source .venv/bin/activate
    python3 -c "import sounddevice as sd; print(); print('Available Audio Devices:'); print('=' * 60); devices = sd.query_devices(); [print(f'{i:2}: {d[\"name\"]}') for i, d in enumerate(devices)]"
    echo ""
    echo -e "${YELLOW}Set input_device_index and output_device_index in config.json${NC}"
fi

echo ""
echo -e "${GRAY}Installation complete. Press Enter to exit...${NC}"
read
