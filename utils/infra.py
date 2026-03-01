import socket
import os
import subprocess
import psutil
import time
import requests
import sys
import aiohttp
import asyncio
from .config import load_config

# --- PORT UTILITIES ---

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_jarvis_ports():
    """Returns a set of all ports defined in config.yaml for Jarvis services."""
    cfg = load_config()
    ports = {cfg['ports']['ollama']}
    if 'vllm' in cfg['ports']:
        ports.add(cfg['ports']['vllm'])
    ports.update(cfg['stt_loadout'].values())
    ports.update(cfg['tts_loadout'].values())
    return ports

# --- SERVICE STATUS (SYNC) ---

def get_service_status(port: int):
    """Synchronous check of a single service status."""
    if not is_port_in_use(port): return "OFF", None
    cfg = load_config()
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
        elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"
        
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            # Check for Stub Signature
            is_stub = "stub" in str(data.get("service", "")).lower() or data.get("stub") is True
            
            # Special parsing for LLM engines
            if port == cfg['ports']['ollama']:
                return "ON", ("Stub" if is_stub else "Ollama")
            if port == cfg['ports'].get('vllm'):
                if is_stub: return "ON", "Stub"
                models = data.get("data", [])
                return "ON", (models[0]["id"] if models else "vLLM")
            
            # Standard Jarvis service status
            raw_name = data.get("model") or data.get("variant") or data.get("service") or "Ready"
            name = f"{raw_name} (Stub)" if is_stub and "stub" not in raw_name.lower() else raw_name
            return ("BUSY" if data.get("status") == "busy" else "ON"), name
        elif response.status_code == 503 and response.json().get("status") == "STARTUP":
            return "STARTUP", "Loading..."
        return "UNHEALTHY", None
    except:
        return "OFF", None

def get_system_health(ports=None, log_paths=None):
    """Consolidated synchronous health check for all or specific services."""
    health_raw = asyncio.run(get_system_health_async(ports=ports, log_paths=log_paths))
    cfg = load_config()
    health = {}
    
    port_map = {
        cfg['ports']['ollama']: {"label": "Ollama", "type": "llm"},
    }
    if 'vllm' in cfg['ports']:
        port_map[cfg['ports']['vllm']] = {"label": "vLLM", "type": "llm"}
    
    for name, port in cfg['stt_loadout'].items(): port_map[port] = {"label": name, "type": "stt"}
    for name, port in cfg['tts_loadout'].items(): port_map[port] = {"label": name, "type": "tts"}

    # Filter port_map if specific ports were requested
    if ports:
        port_map = {p: meta for p, meta in port_map.items() if p in ports}

    for port, meta in port_map.items():
        res = health_raw.get(port, {"status": "OFF", "info": None})
        
        # TRANSITION LOGIC: If a specific port was requested but is currently OFF, 
        # it means we've just updated the registry and the service is STARTING.
        status = res['status']
        if ports and port in ports and status == "OFF":
            status = "STARTUP"
            
        health[port] = {
            "status": status, "info": res['info'],
            "label": meta['label'], "type": meta['type']
        }
    return health

# --- ASYNC INFRASTRUCTURE ---

async def get_service_status_async(session, port: int):
    """Asynchronous version of get_service_status."""
    if not is_port_in_use(port): return port, "OFF", None
    cfg = load_config()
    url = f"http://127.0.0.1:{port}/health"
    if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
    elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"

    try:
        async with session.get(url, timeout=1.0) as response:
            if response.status == 200:
                data = await response.json()
                # Check for Stub Signature
                is_stub = "stub" in str(data.get("service", "")).lower() or data.get("stub") is True
                
                if port == cfg['ports']['ollama']: 
                    return port, "ON", ("Stub" if is_stub else "Ollama")
                if port == cfg['ports'].get('vllm'): 
                    if is_stub: return port, "ON", "Stub"
                    models = data.get("data", [])
                    return port, "ON", (models[0]["id"] if models else "vLLM")
                
                raw_name = data.get("model") or data.get("variant") or data.get("service") or "Ready"
                name = f"{raw_name} (Stub)" if is_stub and "stub" not in raw_name.lower() else raw_name
                return port, ("BUSY" if data.get("status") == "busy" else "ON"), name
            elif response.status == 503:
                data = await response.json()
                if data.get("status") == "STARTUP": return port, "STARTUP", "Loading..."
            return port, "UNHEALTHY", None
    except:
        return port, "OFF", None

async def get_system_health_async(ports=None, log_paths=None):
    """Polls specified or all Jarvis services in parallel, including log error checks."""
    target_ports = ports if ports else get_jarvis_ports()
    async with aiohttp.ClientSession() as session:
        tasks = [get_service_status_async(session, p) for p in target_ports]
        results = await asyncio.gather(*tasks)
    
    health = {r[0]: {"status": r[1], "info": r[2]} for r in results}
    
    # LOG ERROR DETECTION
    if log_paths:
        for port, path in log_paths.items():
            if port in health and health[port]['status'] != "ON":
                if check_log_for_errors(path):
                    health[port]['status'] = "ERROR"
                    health[port]['info'] = "Fatal Error (Check Logs)"
    
    return health

def check_log_for_errors(log_path):
    """Fast-scan the tail of a log file for fatal error signatures."""
    if not log_path or not os.path.exists(log_path):
        return False
        
    error_signatures = [
        "Traceback (most recent call last)",
        "OSError:",
        "HFValidationError",
        "ValueError: No available memory",
        "CUDA Out of Memory",
        "RuntimeError:",
        "AttributeError:",
        "ModuleNotFoundError:",
        "ImportError:",
        "failed to connect to the docker API",
        "is the docker daemon running"
    ]
    
    try:
        with open(log_path, 'rb') as f:
            # Check last 8KB for performance
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            chunk = f.read().decode('utf-8', errors='ignore')
            
            for sig in error_signatures:
                if sig in chunk:
                    return True
    except:
        pass
    return False

async def wait_for_ports_parallel(ports, timeout, require_stub=False):
    if not ports: return True
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        while time.time() - start_time < timeout:
            tasks = [get_service_status_async(session, p) for p in ports]
            results = await asyncio.gather(*tasks)
            # results is list of (port, status, info)
            
            all_on = True
            for r in results:
                p_port, status, info = r
                if status != "ON": 
                    all_on = False; break
                if require_stub and "stub" not in str(info).lower():
                    all_on = False; break
            
            if all_on: return True
            await asyncio.sleep(0.5)
    return False

# --- LIFECYCLE MANAGEMENT ---

def start_server(cmd, loud=False, log_file=None):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    stdout = log_file if log_file else None
    stderr = log_file if log_file else None
    return subprocess.Popen(cmd, creationflags=flags, shell=not isinstance(cmd, list), cwd=project_root, stdout=stdout, stderr=stderr)

def wait_for_port(port: int, timeout: int = 120, process=None) -> bool:
    start_time = time.time()
    has_started_up = False
    while time.time() - start_time < timeout:
        status, info = get_service_status(port)
        if status == "ON": return True
        if status == "STARTUP": has_started_up = True
        if has_started_up and status == "OFF": return False
        if process and process.poll() is not None: return False
        time.sleep(0.2)
    return False

def kill_jarvis_ports(ports_to_kill):
    if not ports_to_kill: return
    ports_to_kill = set(ports_to_kill)
    cfg = load_config()
    
    if cfg['ports']['ollama'] in ports_to_kill and os.name == 'nt':
        subprocess.run(["taskkill", "/F", "/IM", "ollama*", "/T"], capture_output=True)
        time.sleep(1.0)
    
    if cfg['ports'].get('vllm') in ports_to_kill: stop_vllm_docker()

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections(kind='inet'):
                if conn.laddr.port in ports_to_kill:
                    proc.kill(); break
        except (psutil.NoSuchProcess, psutil.AccessDenied): continue
    time.sleep(0.5)

def kill_process_on_port(port: int):
    if not is_port_in_use(port): return True
    kill_jarvis_ports({port})
    return not is_port_in_use(port)

def kill_all_jarvis_services():
    kill_jarvis_ports(get_jarvis_ports())

# --- DOCKER & VLLM ---

def stop_vllm_docker():
    try:
        # Check if container exists (running or stopped)
        res = subprocess.run(["docker", "ps", "-a", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        if "vllm-server" in res.stdout:
            # Force remove is more reliable for cleanup
            subprocess.run(["docker", "rm", "-f", "vllm-server"], capture_output=True)
            # Give Docker a moment to release the namespace
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

# --- LOGS ---

def get_ollama_log_path():
    if os.name == 'nt': return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Ollama', 'server.log')
    return os.path.expanduser('~/.ollama/logs/server.log')
