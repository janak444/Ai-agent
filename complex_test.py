import httpx2
import json

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:latest"

def test_complex_generation():
    print("🚀 Requesting complex software from local LLM (Testing Streaming & Timeout)...")
    prompt = (
        "Create a professional Python-based Personal Finance Tracker. "
        "Requirements: "
        "1. Use a class-based structure. "
        "2. Implement a way to add expenses and income. "
        "3. Implement a way to categorize transactions (e.g., Food, Rent, Salary). "
        "4. Add a function to generate a summary report of total balance and spending per category. "
        "5. Include basic data persistence by saving and loading from a JSON file. "
        "Output ONLY the full source code in a single file. Do not include markdown blocks."
    )

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"temperature": 0.2}
    }

    full_response = ""
    try:
        with httpx2.Client(timeout=900.0) as client:
            with client.stream("POST", OLLAMA_URL, json=payload) as response:
                response.raise_for_status()
                print("🤖 Agent is thinking and streaming:\n" + "-"*40)
                for line in response.iter_lines():
                    if line:
                        # Fix: check if line is already a string (httpx2 might handle decoding)
                        line_decoded = line.decode('utf-8') if isinstance(line, bytes) else line
                        chunk = json.loads(line_decoded)
                        if "message" in chunk:
                            content = chunk["message"].get("content", "")
                            print(content, end="", flush=True)
                            full_response += content
                        if chunk.get("done"):
                            break
                print("\n" + "-"*40)

            # Basic cleaning
            code = full_response
            if "```python" in full_response:
                code = full_response.split("```python")[1].split("```")[0].strip()
            elif "```" in full_response:
                code = full_response.split("```")[1].split("```")[0].strip()

            with open("finance_tracker.py", "w") as f:
                f.write(code)
            print("\n✅ Complex project created successfully! File: finance_tracker.py")

    except Exception as e:
        print(f"\n❌ Error during complex test: {e}")

if __name__ == "__main__":
    test_complex_generation()
