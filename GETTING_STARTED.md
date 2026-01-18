# ARGO — Getting Started

A step-by-step guide to install and run ARGO locally.

## System Requirements

- **OS:** Windows 10/11 (setup optimized for PowerShell)
- **Python:** 3.9 or later
- **Ollama:** Running locally (https://ollama.ai)
- **RAM:** 4GB minimum (8GB+ recommended for larger models)

## Prerequisites

Before starting, ensure you have:

1. **Python 3.9+** installed and in your PATH
   ```powershell
   python --version
   ```

2. **Ollama** installed and the service running
   - Download from https://ollama.ai
   - Run: `ollama serve` in a terminal
   - Verify: `ollama list` (should show available models)
   - Pull a model: `ollama pull mistral` (or use HAL if configured)

3. **Git** (optional, for cloning the repository)

## Installation Steps

### Step 1: Clone or Download ARGO

Clone the repository:
```powershell
git clone <repository-url> argo
cd argo
```

Or download the ZIP and extract it.

### Step 2: Run Setup Script (Windows)

PowerShell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser  # Allow local scripts
.\setup.ps1
```

This script will:
- Check Python version
- Create a virtual environment (`.venv`)
- Install dependencies from `requirements.txt`

### Step 3: Manual Setup (If Script Fails)

If the setup script doesn't work, follow these steps manually:

1. **Create virtual environment:**
   ```powershell
   python -m venv .venv
   ```

2. **Activate virtual environment:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   
   (You should see `(.venv)` at the start of your prompt)

3. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Optional: Install async testing support**
   ```powershell
   pip install pytest-asyncio
   ```

## Running ARGO

### Ensure Ollama is Running

In a separate terminal:
```powershell
ollama serve
```

Or verify it's already running:
```powershell
ollama list
```

### Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### Run ARGO CLI

```powershell
python wrapper/argo.py
```

You'll see a prompt:
```
ARGO >
```

Try a simple command:
```
ARGO > tell me what you are
```

### Run Input Shell (Web Interface)

Start the web-based input shell on `http://localhost:8000`:

```powershell
cd input_shell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 in your browser.

## Running Tests

### Latency Tests

Verify the latency framework is working:
```powershell
python -m pytest tests/test_latency.py -v
```

Expected output: **14 passed, 4 skipped** (skipped tests require pytest-asyncio)

### All Tests

Run the full test suite:
```powershell
python -m pytest tests/ -v
```

### Specific Test Module

Test a specific component:
```powershell
python -m pytest tests/test_budget_enforcer.py -v
python -m pytest tests/test_regression_guard.py -v
```

## Component Architecture

ARGO consists of several components:

### Core Runtime (`runtime/`)

- **latency_controller.py** — Profiling and latency measurement (8 checkpoints, 3 profiles)
- **ollama/hal_chat.py** — Direct Ollama REST API interface

### Wrapper (`wrapper/`)

- **argo.py** — Main CLI interface and orchestration
- **transcription.py** — Whisper-based audio transcription
- **intent.py** — Intent classification and parsing

### Input Shell (`input_shell/`)

- **app.py** — FastAPI web interface
- **requirements.txt** — Web-specific dependencies

### Memory & Storage (`memory/`)

- Conversation logs and preferences
- Baseline latency measurements

## Troubleshooting

### "Python not found"

Make sure Python is installed and in your PATH:
```powershell
python --version
```

If not in PATH, reinstall Python and check "Add Python to PATH" during installation.

### "Ollama connection refused"

Ollama must be running in the background:
```powershell
ollama serve
```

Verify it's running:
```powershell
ollama list
```

### "ModuleNotFoundError: No module named 'requests'"

Ensure you've activated the virtual environment:
```powershell
.\.venv\Scripts\Activate.ps1
```

And that dependencies are installed:
```powershell
pip install -r requirements.txt
```

### "Port 8000 already in use"

If the web interface won't start on port 8000, use a different port:
```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

Then access it at http://127.0.0.1:8001

### "Whisper download fails"

The first time you use Whisper, it downloads a model. This can take a few minutes:
```powershell
python -c "import whisper; whisper.load_model('base')"
```

## File Structure

```
argo/
├── README.md                          # Project overview
├── GETTING_STARTED.md                 # This file
├── ARCHITECTURE.md                    # System architecture details
├── requirements.txt                   # Core Python dependencies
├── setup.ps1                          # Windows setup script
│
├── wrapper/
│   ├── argo.py                        # Main CLI interface
│   ├── transcription.py               # Whisper transcription
│   └── intent.py                      # Intent parsing
│
├── runtime/
│   ├── latency_controller.py          # Profiling framework
│   └── ollama/
│       └── hal_chat.py                # Ollama interface
│
├── input_shell/
│   ├── app.py                         # FastAPI web interface
│   ├── requirements.txt               # Web dependencies
│   └── README.md                      # Web interface docs
│
├── memory/
│   ├── logs/                          # Conversation history
│   └── rag/                           # Retrieval-augmented generation
│
├── tests/
│   ├── test_latency.py                # Latency framework tests
│   ├── test_budget_enforcer.py        # Budget enforcement tests
│   └── test_regression_guard.py       # Regression detection tests
│
├── docs/
│   ├── README.md                      # Documentation index
│   ├── architecture/                  # Architecture deep-dives
│   ├── specs/                         # Feature specifications
│   └── usage/                         # Usage guides
│
└── baselines/
    └── (latency baselines, populated after first run)
```

## Next Steps

1. **Read the Architecture Overview:**
   ```
   Open: ARCHITECTURE.md
   ```

2. **Explore Documentation:**
   ```
   Open: docs/README.md
   ```

3. **Run Examples:**
   - CLI: `python wrapper/argo.py`
   - Web: `cd input_shell && python -m uvicorn app:app --host 127.0.0.1 --port 8000`

4. **Check Latency Profiles:**
   - FAST profile (≤2s first-token, ≤6s total)
   - ARGO profile (≤3s first-token, ≤10s total)
   - VOICE profile (≤3s first-token, ≤15s total)

## Notes for Future Automated Setup

An automated installation script is planned for:
- Dependency checking and installation
- Ollama configuration and model pulling
- Virtual environment creation
- Systemd/Task Scheduler integration for persistent server mode
- Cross-platform support (Windows, Linux, macOS)

For now, manual setup is required. File an issue if you encounter problems.

## Support

For issues or questions:
1. Check [ISSUES_HISTORY.md](ISSUES_HISTORY.md) for common problems
2. Review [docs/README.md](docs/README.md) for detailed documentation
3. Check test files for usage examples

---

**Last Updated:** 2026-01-18  
**Status:** Manual setup verified. Auto-install planned for v1.4.8+
