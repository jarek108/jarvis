import subprocess
import requests
import os

# NOTE: This module now focused strictly on hardware-level metrics and model physics.
# System status and port utilities have moved to utils/infra.py.

def get_vram_estimation(label, model_name):
    """Provides rough VRAM cost estimates for known model variants."""
    m = model_name.lower()
    if "whisper" in m:
        if "tiny" in m: return 0.8
        if "base" in m: return 1.0
        if "small" in m: return 2.0
        if "medium" in m: return 3.5
        if "large" in m: return 6.5
    if "chatterbox" in m:
        if "turbo" in m: return 1.2
        if "multilingual" in m: return 4.5
        if "eng" in m: return 4.0
    return 0.0

def get_gpu_vram_usage():
    """Returns current GPU VRAM usage in GB."""
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"]
        output = subprocess.check_output(cmd, text=True).strip()
        return float(output) / 1024.0
    except:
        return 0.0

_total_vram_cache = None

def get_gpu_total_vram():
    """Returns total GPU VRAM in GB."""
    global _total_vram_cache
    if _total_vram_cache is not None:
        return _total_vram_cache
        
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,nounits,noheader"]
        output = subprocess.check_output(cmd, text=True).strip()
        _total_vram_cache = float(output) / 1024.0
        return _total_vram_cache
    except:
        return 32.0 # Fallback for RTX 5090 if command fails

def get_ollama_vram():
    """Requests VRAM usage from Ollama's active model API."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=1)
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            if models:
                return sum(m.get('size_vram', 0) for m in models) / (1024**3)
    except:
        pass
    return 0.0

def get_loaded_ollama_models():
    """Lists names of models currently hot in VRAM according to Ollama."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp.status_code == 200:
            return [m['name'] for m in resp.json().get('models', [])]
    except:
        pass
    return []

def check_ollama_offload(model_name):
    """Checks if a specific Ollama model is fully offloaded to GPU."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            for m in models:
                if model_name in m['name']:
                    size = m.get('size', 0)
                    vram = m.get('size_vram', 0)
                    return (vram >= size), vram / (1024**3), size / (1024**3)
        return True, 0.0, 0.0
    except:
        return True, 0.0, 0.0
