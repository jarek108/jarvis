import socket
import os
import subprocess
import psutil
import time
import requests
import sys
from .config import load_config

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_server(cmd, loud=False, log_file=None):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # On Windows, list-based Popen is more reliable for complex arguments like JSON
    # if shell=False. However, we use shell=True for some legacy reasons.
    # Let's try to pass the list directly and let Python handle the quoting.
    stdout = log_file if log_file else None
    stderr = log_file if log_file else None
    
    return subprocess.Popen(cmd, creationflags=flags, shell=True, cwd=project_root, stdout=stdout, stderr=stderr)

def wait_for_port(port: int, timeout: int = 120, process=None) -> bool:
    # Local import to avoid circular dependency if get_service_status moves elsewhere
    from .vram import get_service_status
    start_time = time.time()
    has_started_up = False
    
    while time.time() - start_time < timeout:
        status, info = get_service_status(port)
        if status == "ON": return True
        if status == "STARTUP": has_started_up = True
        
        # If it was starting up and now it is OFF, it crashed. Fail fast.
        if has_started_up and status == "OFF":
            print(f"  ↳ ❌ Service on port {port} crashed during startup.")
            return False
        
        # Heartbeat for long boots
        elapsed = int(time.time() - start_time)
        # if elapsed % 10 == 0:
        #    print(f"  ... waiting for port {port} ({elapsed}s elapsed, status: {status})", flush=True)
            
        if process and process.poll() is not None: return False
        time.sleep(1)
    return False

def get_vllm_logs():
    """Retrieves logs from the vllm-server container."""
    try:
        res = subprocess.run(["docker", "logs", "vllm-server"], capture_output=True, text=True)
        return res.stdout + "\n" + res.stderr
    except: return "Could not retrieve Docker logs."

def stop_vllm_docker():
    """Stops the vLLM docker container if it is running."""
    try:
        # Check if container exists
        res = subprocess.run(["docker", "ps", "-a", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        if "vllm-server" in res.stdout:
            subprocess.run(["docker", "stop", "vllm-server"], capture_output=True)
            subprocess.run(["docker", "rm", "vllm-server"], capture_output=True)
            return True
    except: pass
    return False

def is_docker_daemon_running():
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except: return False

def is_vllm_docker_running():
    try:
        res = subprocess.run(["docker", "ps", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        return "vllm-server" in res.stdout
    except: return False

def is_vllm_model_local(model_name):
    # Use environment variable as source of truth per GEMINI.md policy
    hf_cache_base = os.getenv("HF_HOME")
    if not hf_cache_base:
        return False
    
    # Check in multiple possible HF cache locations
    locations = [
        os.path.join(hf_cache_base, "hub"),
        hf_cache_base
    ]
    
    # Model name usually looks like "org/model"
    # HF cache folder looks like "models--org--model"
    safe_name = f"models--{model_name.replace('/', '--')}"
    
    for loc in locations:
        if not os.path.exists(loc): continue
        model_path = os.path.join(loc, safe_name)
        if os.path.exists(model_path):
            # If snapshots exists, it's a standard HF cache
            if os.path.exists(os.path.join(model_path, "snapshots")):
                return True
            # If no snapshots, check if there are blobs or safetensors (flat download)
            if os.path.exists(os.path.join(model_path, "blobs")):
                return True
            # Check for direct safetensors/bin files in case of --local-dir usage
            for root, dirs, files in os.walk(model_path):
                if any(f.endswith((".safetensors", ".bin", ".pt")) for f in files):
                    return True
    
    return False

def kill_process_on_port(port: int):
    try:
        cfg = load_config()
        if port == cfg['ports']['ollama'] and os.name == 'nt':
            # Kill everything related to ollama
            subprocess.run(["taskkill", "/F", "/IM", "ollama*", "/T"], capture_output=True)
            time.sleep(1.0)
        
        # If port is vLLM port, try to stop docker container
        if port == cfg['ports'].get('vllm'):
            stop_vllm_docker()

        # Kill python processes if it's a vLLM or custom server port
        pids = {conn.pid for conn in psutil.net_connections(kind='inet') if conn.laddr.port == port and conn.pid}
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                # If it's a vLLM process, we might want to be more aggressive or specific
                # but general kill usually works.
                for child in proc.children(recursive=True):
                    try: child.kill()
                    except: pass
                proc.kill()
                proc.wait(timeout=2)
            except: pass
        return not is_port_in_use(port)
    except: return not is_port_in_use(port)

def get_jarvis_ports():
    """Returns a set of all ports defined in config.yaml for Jarvis services."""
    cfg = load_config()
    ports = {cfg['ports']['sts'], cfg['ports']['ollama']}
    if 'vllm' in cfg['ports']:
        ports.add(cfg['ports']['vllm'])
    ports.update(cfg['stt_loadout'].values())
    ports.update(cfg['tts_loadout'].values())
    return ports

def kill_all_jarvis_services():
    """Kills every service defined in config.yaml."""
    ports = get_jarvis_ports()
    for port in ports:
        kill_process_on_port(port)
