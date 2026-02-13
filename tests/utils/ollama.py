import requests
import subprocess

def is_model_local(model_name):
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags")
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            return any(model_name in m for m in models)
    except: pass
    return False

def check_and_pull_model(model_name, force_pull=False):
    if is_model_local(model_name): return True
    if not force_pull:
        return False
    
    try:
        print(f"Model {model_name} not found. Pulling (this may take a while)...")
        subprocess.run(["ollama", "pull", model_name], check=True)
        return True
    except:
        return False

def warmup_llm(model_name, visual=False, engine="ollama"):
    print(f"🔥 Warming up {model_name} (Hot-loading weights)...")
    
    if engine == "vllm":
        url = "http://127.0.0.1:8300/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False
        }
    else:
        url = "http://127.0.0.1:11434/api/chat"
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
        requests.post(url, json=payload, timeout=180)
    except Exception as e:
        print(f"⚠️ Warmup failed: {e}")
