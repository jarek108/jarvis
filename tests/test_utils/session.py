import os
import time
import platform
import psutil
import yaml
import subprocess
from utils import load_config, get_hf_home, get_ollama_models

_gpu_info_cache = None
_cpu_info_cache = None

def get_cache_path():
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, "tests", ".system_cache.yaml")

def load_system_cache():
    path = get_cache_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except: pass
    return {}

def save_system_cache(data):
    path = get_cache_path()
    try:
        # Load existing to merge
        existing = load_system_cache()
        existing.update(data)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)
    except: pass

def get_gpu_info():
    """Retrieves GPU model name using nvidia-smi (cached)."""
    global _gpu_info_cache
    if _gpu_info_cache is not None:
        return _gpu_info_cache
    
    cache = load_system_cache()
    if 'gpu' in cache:
        _gpu_info_cache = cache['gpu']
        return _gpu_info_cache
        
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        _gpu_info_cache = res.stdout.strip()
        save_system_cache({'gpu': _gpu_info_cache})
        return _gpu_info_cache
    except:
        return "Unknown GPU"

def get_cpu_info():
    """Retrieves CPU model name (cached)."""
    global _cpu_info_cache
    if _cpu_info_cache is not None:
        return _cpu_info_cache
    
    cache = load_system_cache()
    if 'cpu' in cache:
        _cpu_info_cache = cache['cpu']
        return _cpu_info_cache
        
    try:
        if platform.system() == "Windows":
            # Using wmic to get CPU name on Windows
            res = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True, check=True
            )
            lines = res.stdout.strip().split("\n")
            if len(lines) > 1:
                _cpu_info_cache = lines[1].strip()
                save_system_cache({'cpu': _cpu_info_cache})
                return _cpu_info_cache
        elif platform.system() == "Linux":
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        _cpu_info_cache = line.split(":")[1].strip()
                        save_system_cache({'cpu': _cpu_info_cache})
                        return _cpu_info_cache
    except:
        pass
    
    _cpu_info_cache = platform.processor() or "Unknown CPU"
    return _cpu_info_cache

def get_docker_info():
    """Returns (status, version) for Docker."""
    version = "N/A"
    try:
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True, check=True)
        version = res.stdout.strip().replace("Docker version ", "")
    except:
        return "Missing", "N/A"
    
    try:
        # Check if daemon is responsive
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            return "On", version
        else:
            return "Off", version
    except:
        return "Off", version

def get_ollama_info():
    """Returns (status, version) for Ollama."""
    version = "N/A"
    try:
        res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=True)
        version = res.stdout.strip().replace("ollama version is ", "")
    except:
        return "Missing", "N/A"
    
    try:
        import requests
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
        if resp.status_code == 200:
            return "On", version
        else:
            return "Off", version
    except:
        return "Off", version

def gather_system_info(plan_path):
    """Gathers host machine and test plan metadata."""
    cfg = load_config()
    cache = load_system_cache()
    
    # Git info
    git_hash = "Unknown"
    git_branch = "Unknown"
    try:
        git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    except: pass

    # Plan content
    plan_content = {}
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_content = yaml.safe_load(f)

    # Initial RAM and VRAM snapshots
    import utils.vram
    
    mem = psutil.virtual_memory()
    total_ram = cache.get('ram_total_gb')
    if not total_ram:
        total_ram = round(mem.total / (1024**3), 2)
        save_system_cache({'ram_total_gb': total_ram})
    
    used_ram = round(mem.used / (1024**3), 2)
    
    total_vram = cache.get('vram_total_gb')
    if not total_vram:
        total_vram = round(utils.vram.get_gpu_total_vram(), 2)
        save_system_cache({'vram_total_gb': total_vram})
        
    used_vram = round(utils.vram.get_gpu_vram_usage(), 2)

    d_status, d_ver = get_docker_info()
    o_status, o_ver = get_ollama_info()

    info = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": {
            "os": platform.platform(),
            "cpu": get_cpu_info(),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": total_ram,
            "ram_used_gb": used_ram,
            "gpu": get_gpu_info(),
            "vram_total_gb": total_vram,
            "vram_used_gb": used_vram,
            "docker": {"status": d_status, "version": d_ver},
            "ollama": {"status": o_status, "version": o_ver},
        },
        "environment": {
            "HF_HOME": get_hf_home(silent=True),
            "OLLAMA_MODELS": get_ollama_models(silent=True),
        },
        "git": {
            "hash": git_hash,
            "branch": git_branch
        },
        "plan": plan_content
    }
    return info

def init_session(plan_path):
    """Initializes a new test session directory and system info file."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_id = f"RUN_{timestamp}"
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    session_dir = os.path.join(project_root, "tests", "logs", session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    system_info = gather_system_info(plan_path)
    with open(os.path.join(session_dir, "system_info.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(system_info, f, sort_keys=False)
        
    return session_dir, session_id
