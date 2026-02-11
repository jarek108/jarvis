import requests
import subprocess

def check_and_pull_model(model_name):
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags")
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            if any(model_name in m for m in models): return True
        print(f"Model {model_name} not found. Pulling (this may take a while)...")
        subprocess.run(["ollama", "pull", model_name], check=True)
        return True
    except:
        return False

def warmup_llm(model_name, visual=False):
    print(f"🔥 Warming up {model_name} (Hot-loading weights)...")
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False
    }
    if visual:
        tiny_img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        payload["messages"][0]["images"] = [tiny_img]
        print("  ↳ 👁️ Performing Visual Encoder Warmup...")
    try:
        requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
    except Exception as e:
        print(f"⚠️ Warmup failed: {e}")
