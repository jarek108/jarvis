import socket
import os
import subprocess
import psutil
import time
import requests
import sys
from .config import load_config

import aiohttp
import asyncio

async def get_service_status_async(session, port: int):
    """Asynchronous version of get_service_status for batch checks."""
    # PRE-FLIGHT: If port isn't even open, don't waste time on a request + timeout
    if not is_port_in_use(port):
        return port, "OFF", None
    
    cfg = load_config()
    url = f"http://127.0.0.1:{port}/health"
    if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
    elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"

    try:
        # We know it's in use, so a 1s timeout is safe for a local responsive server
        async with session.get(url, timeout=1.0) as response:
            if response.status == 200:
                data = await response.json()
                if port == cfg['ports']['ollama']: return port, "ON", "Ollama"
                if port == cfg['ports'].get('vllm'): 
                    models = data.get("data", [])
                    return port, "ON", (models[0]["id"] if models else "vLLM")
                name = data.get("model") or data.get("variant") or "Ready"
                return port, ("BUSY" if data.get("status") == "busy" else "ON"), name
            elif response.status == 503:
                data = await response.json()
                if data.get("status") == "STARTUP": return port, "STARTUP", "Loading..."
            return port, "UNHEALTHY", None
    except Exception:
        if port == cfg['ports']['ollama'] or port == cfg['ports'].get('vllm'):
            return port, "STARTUP", "Connecting..."
        return port, "OFF", None

async def get_system_health_async():
    """Polls all Jarvis services in parallel."""
    ports = get_jarvis_ports()
    async with aiohttp.ClientSession() as session:
        tasks = [get_service_status_async(session, p) for p in ports]
        results = await asyncio.gather(*tasks)
    return {r[0]: {"status": r[1], "info": r[2]} for r in results}

async def wait_for_ports_parallel(ports, timeout=120):
    """Waits for multiple ports to be ON in parallel."""
    if not ports: return True
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        while time.time() - start_time < timeout:
            tasks = [get_service_status_async(session, p) for p in ports]
            results = await asyncio.gather(*tasks)
            # Check if all statuses are 'ON'
            if all(r[1] == "ON" for r in results):
                return True
            await asyncio.sleep(0.5)
    return False

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_server(cmd, loud=False, log_file=None):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    stdout = log_file if log_file else None
    stderr = log_file if log_file else None
    
    # If cmd is a list, use shell=False for better reliability on Windows
    use_shell = not isinstance(cmd, list)
    return subprocess.Popen(cmd, creationflags=flags, shell=use_shell, cwd=project_root, stdout=stdout, stderr=stderr)

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
        time.sleep(0.2)
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

def kill_jarvis_ports(ports_to_kill):
    """Efficiently kills processes on multiple ports in a single pass."""
    if not ports_to_kill: return
    
    ports_to_kill = set(ports_to_kill)
    cfg = load_config()
    
    # Special handling for Ollama on Windows
    ollama_port = cfg['ports']['ollama']
    if ollama_port in ports_to_kill and os.name == 'nt':
        if is_port_in_use(ollama_port):
            subprocess.run(["taskkill", "/F", "/IM", "ollama*", "/T"], capture_output=True)
            time.sleep(0.5)
        ports_to_kill.remove(ollama_port)
    
    # Special handling for vLLM Docker
    vllm_port = cfg['ports'].get('vllm')
    if vllm_port in ports_to_kill:
        stop_vllm_docker()
        ports_to_kill.remove(vllm_port)

    if not ports_to_kill: return

    try:
        # Use process_iter which is generally faster on Windows than net_connections
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Only check connections if it's likely a python or service process
                # this filters out thousands of irrelevant system processes
                name = proc.info['name'].lower()
                if 'python' in name or 'ollama' in name or 'uvicorn' in name:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port in ports_to_kill:
                            proc.kill()
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Short breather for OS to reclaim ports
        time.sleep(0.3)
    except Exception:
        pass

def kill_process_on_port(port: int):
    try:
        if not is_port_in_use(port): return True
        kill_jarvis_ports({port})
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
    kill_jarvis_ports(ports)
