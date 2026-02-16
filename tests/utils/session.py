import os
import time
import platform
import psutil
import yaml
import subprocess
from .config import load_config, get_hf_home, get_ollama_models

def get_gpu_info():
    """Retrieves GPU model name using nvidia-smi."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    except:
        return "Unknown GPU"

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

    info = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": {
            "os": platform.platform(),
            "cpu_count": psutil.cpu_count(logical=True),
            "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "gpu": get_gpu_info(),
        },
        "environment": {
            "HF_HOME": get_hf_home(),
            "OLLAMA_MODELS": get_ollama_models(),
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
