# Mimo-Agentic IDE Coding Instructions

## Project Overview
Mimo-Agentic IDE is a multimodal AI-powered engineering environment. It leverages local LLMs via Ollama to perform autonomous software engineering tasks, including code generation, file manipulation, and shell execution.

## Architecture & Core Components
- **`run_gui.py`**: The primary entry point. A `customtkinter` GUI that implements a ReAct (Thought-Action-Observation) loop.
- **`run_agent.py`**: A CLI-based version of the agent engine for direct model interaction and code generation.
- **Agent Loop**: Uses a structured prompt requiring the agent to output `Thought:`, `Action:`, and `Final Answer:`.
- **Multimodal Integration**: Uses a vision model (default: `llava`) to describe images, which is then fed into the primary agent's context as a technical observation.

## Key Patterns & Conventions
- **Tool Use**: The agent interacts with the system via a predefined set of tools:
  - `read_file(path)`
  - `write_file(path, content)`
  - `execute_command(command)`
  - `list_files()`
- **Path Handling**: All file paths are resolved relative to the `project_root`. The system enforces a security boundary to prevent access outside this root.
- **Local Model Integration**: Communicates with Ollama via `http://localhost:11434/api/chat` (or `/api/generate` for vision).
- **Lazy Loading**: Heavy libraries (e.g., `whisper`, `pyaudio`, `numpy`) are imported inside getter functions (e.g., `get_whisper()`) to prevent GUI startup freezes.

## Developer Workflows
- **Running the IDE**: `python run_gui.py`
- **Running the CLI Agent**: `python run_agent.py`
- **Testing Connectivity**: `python test_agent.py` (verifies Ollama connection and model availability).
- **Environment**: Uses a virtual environment located in `agent-env/`.

## Implementation Guidelines for AI Agents
- **Maintain ReAct Structure**: When modifying the agent loop, ensure the `Thought -> Action -> Observation` cycle remains intact.
- **Security First**: Always use `resolve_path` when implementing new file-system tools to maintain the project root boundary.
- **UI Stability**: When adding GUI elements, use `self.update()` or `self.update_idletasks()` to ensure macOS window stability.
- **Model Compatibility**: Ensure model names match those in the `models_inventory` (e.g., `qwen3-coder:30b`, `deepseek-r1:latest`).
