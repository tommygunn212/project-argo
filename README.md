# Argo

A local AI conversational system with memory, preferences, and deterministic recall.

## What is Argo?

Argo is a command-line AI assistant that remembers conversations, learns your preferences, and gives you precise control over how it behaves. It runs locally using Ollama and requires no external API calls or subscriptions.

## What It Does

- **Memory**: Stores interactions with TF-IDF-based retrieval and topic fallback for context-aware conversations
- **Preferences**: Learns your tone, verbosity, humor style, and response structure preferences
- **Recall Mode**: Deterministic meta-query handling (e.g., "what did we talk about?") without model inference
- **Interactive CLI**: Both single-shot and multi-turn conversation modes with natural flow
- **Conversation Browsing**: Read-only access to past sessions by date or topic

## Quick Start

### Prerequisites

- Python 3.9+
- Ollama running (`ollama serve`)
- llama3.1:8b model (`ollama pull llama3.1`)

### Setup

```bash
git clone https://github.com/YOUR-REPO/argo.git
cd argo
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
ai
```

**Windows users:** Run `./setup.ps1` instead for automated setup.

## Usage

### Single-shot mode
```powershell
ai "Why do eggs get hard when boiled?"
```

### Interactive mode (recommended)
```powershell
ai
argo > Why do eggs get hard when boiled?
argo > What about frying?
argo > exit
```

### Conversation browsing
```powershell
ai
argo > list conversations
argo > show topic eggs
argo > summarize eggs
argo > exit
```

## Exiting

Type `exit` or `quit` in interactive mode. Single-shot mode exits automatically.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, and design principles.

## License

MIT
