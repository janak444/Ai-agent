import httpx2
import json

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.8:27b-mtp-q4_K_M" # Using installed local model

def test_connection():
    print(f"🧪 Testing connection to Ollama with model: {MODEL}...")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say 'Connection Successful!' in 3 words."}],
        "stream": False
    }

    try:
        with httpx2.Client(timeout=30.0) as client:
            response = client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            result = response.json()["message"]["content"]
            print(f"✅ Success! Response from Ollama: {result}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\nPossible reasons:")
        print("1. Ollama is not running on your machine.")
        print(f"2. The model '{MODEL}' is not downloaded (try: ollama pull {MODEL}).")

if __name__ == "__main__":
    test_connection()
