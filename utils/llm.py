import requests
import subprocess
import os

def is_model_local(model_name):
    # 1. Try API first
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            # Ollama tags can be model:latest or just model
            if ":" not in model_name:
                return any(model_name == m.split(":")[0] for m in models)
            return any(model_name in m for m in models)
    except: pass

    # 2. Try Filesystem (Robust fallback)
    from .config import get_ollama_models
    models_dir = get_ollama_models()
    if models_dir and os.path.exists(models_dir):
        # Ollama structure: manifests/registry.ollama.ai/library/model/tag
        # or manifests/registry.ollama.ai/author/model/tag
        manifest_root = os.path.join(models_dir, "manifests", "registry.ollama.ai")
        if os.path.exists(manifest_root):
            # Flatten search for model_name
            target = model_name
            if ":" not in target: target += ":latest"
            parts = target.split(":")
            name_parts = parts[0].split("/")
            if len(name_parts) == 1:
                # library/model
                rel_path = os.path.join("library", name_parts[0], parts[1])
            else:
                # author/model
                rel_path = os.path.join(name_parts[0], name_parts[1], parts[1])
            
            if os.path.exists(os.path.join(manifest_root, rel_path)):
                return True
    
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
            import base64
            # Use a real image from the project to ensure valid headers/pixels
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vlm", "input_data", "jarvis_logo.png")
            if os.path.exists(img_path):
                with open(img_path, "rb") as f_img:
                    tiny_img = base64.b64encode(f_img.read()).decode('utf-8')
                payload["messages"][0]["images"] = [tiny_img]
                print("  ↳ 👁️ Performing Visual Encoder Warmup...")
            else:
                print("  ↳ ⚠️ Warmup image not found, skipping visual warmup.")
            
    try:
        # Increased timeout for large 30B+ VLM models
        resp = requests.post(url, json=payload, timeout=300)
        if resp.status_code != 200:
            print(f"⚠️ Warmup failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"⚠️ Warmup failed (likely timeout): {e}")
