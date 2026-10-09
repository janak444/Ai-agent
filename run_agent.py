import os
import glob
import json
import httpx2

OLLAMA_URL = "http://localhost:11434/api/chat"

def scan_workspace():
    """Scans the local desktop folder to list available codebase fragments."""
    files = [f for f in glob.glob("*") if os.path.isfile(f) and f != "run_agent.py"]
    return files

def prompt_local_model(model_name, task):
    """Sends the execution string straight to the selected local Ollama core."""
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert autonomous software engineer and data architect agent. "
                    "When building complex software systems, output the complete, functional python "
                    "source code enclosed inside a clean ```python markdown block."
                )
            },
            {
                "role": "user",
                "content": task
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }
    
    with httpx2.Client(timeout=300.0) as client:
        response = client.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]

if __name__ == "__main__":
    print("🤖 Waking up Multi-Model Local Agent Engine...")
    
    # Strictly bound to the exact names verified in your ollama inventory list
    models_inventory = {
        "1": "qwen3-coder:30b",
        "2": "deepseek-r1:latest",
        "3": "freebuff-mimo:latest",
        "4": "llama3.2:latest"
    }
    
    print("\n🗂️  Available Local Brain Options:")
    for key, name in models_inventory.items():
        print(f"  [{key}] {name}")
        
    choice = input("\n👉 Select a model brain to run this step (1-4): ").strip()
    selected_model = models_inventory.get(choice, "qwen3-coder:30b")
    
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
            agent_output = prompt_local_model(selected_model, user_task)
            print(f"\n🤖 Agent Output:\n{agent_output}")
            
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

