# Devsoft-Agentic IDE

A local-first, high-speed agentic coding IDE powered by Ollama. Engineered with Antigravity-style workflows for rapid, autonomous software development.

## Overview

Devsoft-Agentic IDE is a desktop application that connects to a local Ollama server and provides two distinct operating modes:
- **⚡ Fast Mode**: Instant direct agent execution. Immediately edits code, runs commands, tests, and responds in 1 turn without unnecessary multi-stage planning roundtrips.
- **🧠 Architect Mode**: Complete autonomous mission pipeline (plan → execute → verify → review → summarize) for large architectural changes.

Features:
- **Antigravity Dark Theme**: Modern slate/charcoal interface with crisp typography and subtle borders.
- **Interactive Tool Cards**: Visual cards for `edit_file`, `write_file`, `run_command`, `git_diff`, etc., with live status badges.
- **One-Click Code Copy**: Monospace code blocks with line numbers and instant `[📋 Copy]` buttons.
- **Collapsible Reasoning**: Chain-of-thought and model thinking kept cleanly folded so code answers stay front and center.
- **Context Injection (`@file`)**: Type `@filename` or click the `📎 Active File` pill to automatically inject source files into your prompt.
- **Slash Commands**: Quick shortcuts like `/fast`, `/plan`, `/fix`, `/test`, `/diff`, `/clear`, `/help`.
- **Prompt History Navigation**: Press `↑` and `↓` inside the chat prompt to recall previous prompts.
- **Live Speed & Metric Tracking**: Displays real-time tokens/sec, prompt tokens, and duration in the status bar.

Recommended model: **qwen3.8:27b-mtp-q4_K_M** or **qwen3-coder:30b** (fastest local options on Apple Silicon with thinking mode off).

## Components

| File | Role |
| --- | --- |
| `run_gui.py` | Devsoft-Agentic IDE desktop application |
| `run_agent.py` | Standalone CLI agent runner (no GUI) |
| `test_agent.py` | Connectivity and generation tests |
| `complex_test.py` | Complex code-generation test |
| `agent-env/` | Python virtual environment with dependencies |

The full agent engine lives in the companion repository (`ai-agent/agent.py`) and is invoked by the GUI via `DEVSOFT_AGENT_SCRIPT` / `DEVSOFT_AGENT_PY` environment variables (defaults point at the local checkout).

## Requirements

- macOS or Windows
- [Ollama](https://ollama.com) running locally (`ollama serve`)
- Python 3.10+
- A local coding model, e.g. `ollama pull qwen3.8:27b`

## Setup

```bash
# 1. Create a virtual environment
python3 -m venv agent-env
source agent-env/bin/activate          # Windows: agent-env\Scripts\activate

# 2. Install dependencies
pip install customtkinter httpx2 pillow ollama

# 3. Pull the recommended model
ollama pull qwen3.8:27b

# 4. Launch the IDE
python run_gui.py
```

## Building a Desktop App

PyInstaller packages the IDE into a standalone `.app` (macOS) or `.exe` (Windows):

```bash
pip install pyinstaller
pyinstaller Devsoft-Agentic.spec
```

- macOS: `dist/Devsoft-Agentic IDE.app`
- Windows: `dist/Devsoft-Agentic IDE/Devsoft-Agentic IDE.exe`

A GitHub Actions workflow (`.github/workflows/build-desktop.yml`) builds both platforms automatically on tag push.

## Settings

Open **⚙ Settings** in the IDE to configure:

- Ollama host URL
- Context window (`num_ctx`)
- Temperature
- Keep-alive duration
- Max output tokens
- Model thinking mode (off = fastest responses)
- Auto-approve actions

Settings persist in `~/.devsoft_ide_settings.json` (legacy `~/.mimo_ide_*` files are migrated automatically on first launch).

## License

See repository for license details.
