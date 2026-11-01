import os
import sys
import glob
import json

try:
    import httpx2
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _venv_py = os.path.join(_here, "agent-env", "bin", "python3")
    if not os.path.exists(_venv_py):
        _venv_py = os.path.join(_here, "agent-env", "Scripts", "python.exe")
    if os.path.exists(_venv_py) and os.path.abspath(sys.executable) != os.path.abspath(_venv_py):
        os.execv(_venv_py, [_venv_py] + sys.argv)
    raise

OLLAMA_URL = "http://localhost:11434/api/chat"

def scan_workspace():
    """Scans the local desktop folder to list available codebase fragments."""
    files = [f for f in glob.glob("*") if os.path.isfile(f) and f != "run_agent.py"]
    return files

def get_available_models():
    """Dynamically queries Ollama for available models or falls back to defaults."""
    try:
        with httpx2.Client(timeout=5.0) as client:
            r = client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
                if models:
                    return {str(i + 1): name for i, name in enumerate(models)}
    except Exception:
        pass
    return {
        "1": "qwen3.8:27b-mtp-q4_K_M",
        "2": "qwen3-coder:30b",
        "3": "llava:latest",
        "4": "deepseek-r1:latest",
    }

def prompt_local_model(model_name, task, history=None):
    """Sends the execution string to the selected local Ollama core with streaming enabled."""
    if history is None:
        history = []

    messages = [
        {
            "role": "system",
            "content": (
                "You are Antigravity, an expert autonomous software engineer and pair programming agent. "
                "Respond with fast, precise, production-grade solutions. "
                "When writing software or scripts, output complete, functional source code enclosed inside "
                "clean markdown code blocks (e.g. ```python)."
            )
        }
    ]

    messages.extend(history)
    messages.append({"role": "user", "content": task})

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "keep_alive": "60m",
        "options": {
            "temperature": 0.1,
            "num_ctx": 16384
        }
    }

    full_response = ""
    # Increased timeout to 900 seconds (15 minutes)
    with httpx2.Client(timeout=900.0) as client:
        with client.stream("POST", OLLAMA_URL, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode('utf-8'))
                    if "message" in chunk:
                        content = chunk["message"].get("content", "")
                        print(content, end="", flush=True)
                        full_response += content
                    if chunk.get("done"):
                        break
    return full_response

if __name__ == "__main__":
    print("🤖 Waking up Antigravity Local Agent Engine...")

    models_inventory = get_available_models()

    print("\n🗂️  Available Local Brain Options:")
    for key, name in models_inventory.items():
        print(f"  [{key}] {name}")

    default_choice = "1"
    choice = input(f"\n👉 Select a model brain to run this step (default: [{default_choice}] {models_inventory.get(default_choice, '')}): ").strip()
    selected_model = models_inventory.get(choice if choice else default_choice, "qwen3.8:27b-mtp-q4_K_M")

    # Initialize session history
    session_history = []

    print(f"\n🧠 Active Engine locked to: '{selected_model}'")
    print(f"📁 Local Files Detected: {scan_workspace()}")
    print("--- Enter your application requirements (Type 'exit' to quit) ---")

    while True:
        user_task = input("\n👉 User: ")
        if user_task.lower() in ['exit', 'quit']:
            break
        if not user_task.strip():
            continue

        print(f"\n🧠 Thinking (Processing Locally via {selected_model})...")
        try:
            # The prompt_local_model now handles the printing via streaming
            agent_output = prompt_local_model(selected_model, user_task, history=session_history)
            print() # Add a newline after the streamed response ends

            # Update session history with the user prompt and agent response
            session_history.append({"role": "user", "content": user_task})
            session_history.append({"role": "assistant", "content": agent_output})

            if "```python" in agent_output:
                print("\n💡 I detected python code output! Would you like to save this file? (yes/no)")
                save_choice = input("👉 Choice: ")
                if save_choice.lower() in ['yes', 'y']:
                    code_block = agent_output.split("```python")[1].split("```")[0].strip()
                    filename = input("💾 Enter filename to save as (e.g., complex_app.py): ")
                    with open(filename, 'w') as f:
                        f.write(code_block)
                    print(f"✅ Created and saved '{filename}' cleanly inside your workspace folder!")
        except Exception as e:
            print(f"\n❌ Local Connection Error: {e}")
            print("Tip: Make sure the Ollama server is running in the background.")

