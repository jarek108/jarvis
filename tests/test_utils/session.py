import os
import time
import platform
import psutil
import yaml
import subprocess
from utils import load_config, get_hf_home, get_ollama_models

_gpu_info_cache = None
_cpu_info_cache = None

def get_gpu_info():
    """Retrieves GPU model name using nvidia-smi (cached)."""
    global _gpu_info_cache
    if _gpu_info_cache is not None:
        return _gpu_info_cache
        
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        _gpu_info_cache = res.stdout.strip()
        return _gpu_info_cache
    except:
        return "Unknown GPU"

def get_cpu_info():
    """Retrieves CPU model name (cached)."""
    global _cpu_info_cache
    if _cpu_info_cache is not None:
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
                return _cpu_info_cache
        elif platform.system() == "Linux":
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        _cpu_info_cache = line.split(":")[1].strip()
                        return _cpu_info_cache
    except:
        pass
    
    _cpu_info_cache = platform.processor() or "Unknown CPU"
    return _cpu_info_cache

def gather_system_info(plan_path):
    """Gathers host machine and test plan metadata."""
    cfg = load_config()
    
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
    from utils.vram import get_gpu_total_vram, get_gpu_vram_usage
    
    mem = psutil.virtual_memory()
    total_ram = mem.total / (1024**3)
    used_ram = mem.used / (1024**3)
    
    total_vram = get_gpu_total_vram()
    used_vram = get_gpu_vram_usage()

    info = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": {
            "os": platform.platform(),
            "cpu": get_cpu_info(),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": round(total_ram, 2),
            "ram_used_gb": round(used_ram, 2),
            "gpu": get_gpu_info(),
            "vram_total_gb": round(total_vram, 2),
            "vram_used_gb": round(used_vram, 2),
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
