import subprocess
import requests
from .infra import is_port_in_use
from .config import load_config

def get_vram_estimation(label, model_name):
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

def get_ollama_vram():
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
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp.status_code == 200:
            return [m['name'] for m in resp.json().get('models', [])]
    except:
        pass
    return []

def get_service_status(port: int):
    if not is_port_in_use(port): return "OFF", None
    cfg = load_config()
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
        elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"
        
        response = requests.get(url, timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            if port == cfg['ports']['ollama']:
                vram = get_ollama_vram()
                loaded = get_loaded_ollama_models()
                model_info = loaded[0] if loaded else "Ollama Core"
                v_str = f"({vram:.1f}GB)" if vram > 0 else ""
                return "ON", f"{model_info} {v_str}".strip()
            
            if port == cfg['ports'].get('vllm'):
                models = data.get("data", [])
                if not models:
                    return "STARTUP", "Initializing..."
                model_name = models[0]["id"] if models else "vLLM Core"
                return "ON", f"{model_name}"

            name = data.get("model") or data.get("variant") or "Ready"
            vram = get_vram_estimation(data.get("type", ""), name)
            v_str = f"({vram:.1f}GB)" if vram > 0 else ""
            return ("BUSY" if data.get("status") == "busy" else "ON"), f"{name} {v_str}".strip()
        elif response.status_code == 503 and response.json().get("status") == "STARTUP":
            return "STARTUP", "Loading..."
        return "UNHEALTHY", None
    except requests.exceptions.ConnectionError:
        # If it's an LLM port, treat connection error as STARTUP (container might be booting)
        if port == cfg['ports']['ollama'] or port == cfg['ports'].get('vllm'):
            return "STARTUP", "Connecting..."
        return "OFF", None
    except:
        return "UNHEALTHY", None

def get_system_health():
    cfg = load_config()
    health = {}
    sts_status, sts_info = get_service_status(cfg['ports']['sts'])
    health[cfg['ports']['sts']] = {"status": sts_status, "info": sts_info, "label": "sts", "type": "sts"}
    
    ollama_status, ollama_info = get_service_status(cfg['ports']['ollama'])
    health[cfg['ports']['ollama']] = {"status": ollama_status, "info": ollama_info, "label": "Ollama", "type": "llm"}
    
    if 'vllm' in cfg['ports']:
        vllm_status, vllm_info = get_service_status(cfg['ports']['vllm'])
        health[cfg['ports']['vllm']] = {"status": vllm_status, "info": vllm_info, "label": "vLLM", "type": "llm"}

    for name, port in cfg['stt_loadout'].items():
        status, info = get_service_status(port)
        health[port] = {"status": status, "info": info, "label": name, "type": "stt"}
    for name, port in cfg['tts_loadout'].items():
        status, info = get_service_status(port)
        health[port] = {"status": status, "info": info, "label": name, "type": "tts"}
    return health

def get_gpu_vram_usage():
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"]
        output = subprocess.check_output(cmd, text=True).strip()
        return float(output) / 1024.0
    except:
        return 0.0

def get_gpu_total_vram():
    """Returns total GPU VRAM in GB."""
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,nounits,noheader"]
        output = subprocess.check_output(cmd, text=True).strip()
        return float(output) / 1024.0
    except:
        return 32.0 # Fallback for RTX 5090 if command fails

def check_ollama_offload(model_name):
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
