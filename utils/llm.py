import requests
import subprocess
import os
from .console import ensure_utf8_output

ensure_utf8_output()

def is_model_local(model_name):
    # 1. Try API first
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            # Ollama tags can be model:latest or just model
            target_base = model_name.split(':')[0].lower()
            return any(target_base in m.lower() for m in models)
    except: pass

    # 2. Try Filesystem (Robust fallback)
    from .config import get_ollama_models
    models_dir = get_ollama_models()
    if models_dir and os.path.exists(models_dir):
        manifest_root = os.path.join(models_dir, "manifests", "registry.ollama.ai")
        if os.path.exists(manifest_root):
            # Normalization: handle qwen2.5-0.5b-instruct vs qwen2.5:0.5b
            target = model_name.lower().split(':')[0].split('/')[-1]
            clean_target = target.replace('-instruct', '').replace('-fp16', '').replace('-q4_k_m', '').replace('.', '').replace('-', '')
            
            for root, dirs, files in os.walk(manifest_root):
                for f in files:
                    parent = os.path.basename(root).lower()
                    combined = f"{parent}{f}".lower().replace('.', '').replace('-', '')
                    if clean_target in combined or combined in clean_target:
                        return True
                    
                    # Last resort: common name match
                    if any(p in combined for p in ["qwen", "llama", "mistral", "phi", "gemma"]) and \
                       any(p in target for p in ["qwen", "llama", "mistral", "phi", "gemma"]):
                        # If both are qwen, it's likely a match for our local dev purposes
                        if ("qwen" in target and "qwen" in combined): return True
    
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
    
    from .config import load_config
    cfg = load_config()
    timeout = cfg.get('system', {}).get('llm_warmup_timeout', 300)
    
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
        # Dynamic timeout from config for large 30B+ VLM models
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code != 200:
            print(f"⚠️ Warmup failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"⚠️ Warmup failed (likely timeout): {e}")
