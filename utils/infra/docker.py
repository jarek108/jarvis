import os
import subprocess
import time

def stop_vllm_docker():
    try:
        res = subprocess.run(["docker", "ps", "-a", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        if "vllm-server" in res.stdout:
            subprocess.run(["docker", "rm", "-f", "vllm-server"], capture_output=True)
            time.sleep(1.0)
            return True
    except: pass
    return False

def is_docker_daemon_running():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except: return False

def is_vllm_docker_running():
    try:
        res = subprocess.run(["docker", "ps", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        return "vllm-server" in res.stdout
    except: return False

def is_vllm_model_local(model_name):
    hf_cache_base = os.getenv("HF_HOME")
    if not hf_cache_base: return False
    locations = [os.path.join(hf_cache_base, "hub"), hf_cache_base]
    targets = [model_name, model_name.replace('/', '--'), f"models--{model_name.replace('/', '--')}"]
    
    for loc in locations:
        if not os.path.exists(loc): continue
        for t in targets:
            model_path = os.path.join(loc, t)
            if os.path.exists(model_path):
                if os.path.exists(os.path.join(model_path, "snapshots")): return True
                if os.path.exists(os.path.join(model_path, "blobs")): return True
                for root, dirs, files in os.walk(model_path):
                    if any(f.endswith((".safetensors", ".bin", ".pt")) for f in files): return True
    return False

def get_vllm_logs():
    try:
        res = subprocess.run(["docker", "logs", "vllm-server"], capture_output=True, text=True)
        return res.stdout + "\n" + res.stderr
    except: return "Could not retrieve Docker logs."
