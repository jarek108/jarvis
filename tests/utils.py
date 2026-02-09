import socket
import time
import psutil
import yaml
import os
import requests
import subprocess
from loguru import logger

def load_config():
    # Find config.yaml relative to this file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_service_status(port: int):
    """
    Returns the state of a service on a given port.
    States: ON, OFF, UNHEALTHY, BUSY
    """
    if not is_port_in_use(port):
        return "OFF"
    
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == 11434: # Ollama special case
            url = f"http://127.0.0.1:{port}/api/tags"
            
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "busy":
                return "BUSY"
            return "ON"
        elif response.status_code == 503:
            data = response.json()
            if data.get("status") == "STARTUP":
                return "STARTUP"
            return "UNHEALTHY"
        else:
            return "UNHEALTHY"
    except:
        return "UNHEALTHY"

def get_ollama_info():
    """
    Returns detailed info about Ollama models.
    - downloaded: List of all available models
    - resident: List of models currently in VRAM
    """
    info = {"downloaded": [], "resident": []}
    try:
        # 1. Get all downloaded models
        resp_tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if resp_tags.status_code == 200:
            info["downloaded"] = [m['name'] for m in resp_tags.json().get('models', [])]
        
        # 2. Get models in VRAM
        resp_ps = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp_ps.status_code == 200:
            info["resident"] = [m['name'] for m in resp_ps.json().get('models', [])]
    except:
        pass
    return info

def check_ollama_model(model_name: str):
    """Checks if a specific model is installed in Ollama."""
    info = get_ollama_info()
    models = info["downloaded"]
    return model_name in models or f"{model_name}:latest" in models

def get_system_health():
    """Probes all configured ports and returns a status map."""
    cfg = load_config()
    health = {}
    
    # 1. System Services
    ollama_status = get_service_status(cfg['ports']['llm'])
    ollama_info = get_ollama_info() if ollama_status == "ON" else {"downloaded": [], "resident": []}
    
    health["Ollama"] = {
        "status": ollama_status,
        "port": cfg['ports']['llm'],
        "model_installed": check_ollama_model("gpt-oss:20b"),
        "downloaded_models": ollama_info["downloaded"],
        "resident_models": ollama_info["resident"]
    }
    
    # 2. STT Loadout
    for name, port in cfg['stt_loadout'].items():
        health[f"STT-{name}"] = {"status": get_service_status(port), "port": port}
        
    # 3. TTS Loadout
    for name, port in cfg['tts_loadout'].items():
        health[f"TTS-{name}"] = {"status": get_service_status(port), "port": port}
        
    return health

def start_server(cmd, loud=False):
    """
    Starts a server process.
    If loud=False (default), it suppresses the console window on Windows.
    """
    flags = 0
    if not loud and os.name == 'nt':
        # CREATE_NO_WINDOW = 0x08000000
        flags = 0x08000000
    else:
        flags = subprocess.CREATE_NEW_CONSOLE

    # Use shell=True to allow resolving binaries in PATH (like 'ollama')
    # When shell=True, it is safer/better to pass cmd as a string on Windows
    final_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd]) if isinstance(cmd, list) else cmd
    return subprocess.Popen(final_cmd, creationflags=flags, shell=True)

def wait_for_port(port: int, timeout: int = 60, process=None) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        if get_service_status(port) == "ON":
            return True
        if process and process.poll() is not None:
            logger.error(f"Process for port {port} died unexpectedly.")
            return False
        time.sleep(1)
    return False

def kill_process_on_port(port: int):
    """
    Aggressively finds and kills ANY process on the given port and its children.
    Silently handles cases where processes vanish during the cleanup (race conditions).
    Only logs an error if the port remains busy after the attempt.
    """
    try:
        # Special case for Ollama on Windows: it often has a tray app protector
        if port == 11434 and os.name == 'nt':
            os.system("taskkill /F /IM ollama* /T > nul 2>&1")
            time.sleep(0.5)

        # 1. Collect all PIDs currently holding the port
        pids_to_kill = set()
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.pid:
                pids_to_kill.add(conn.pid)

        if not pids_to_kill:
            return True

        # 2. Attempt to wipe out each process family
        for pid in pids_to_kill:
            try:
                parent = psutil.Process(pid)
                logger.info(f"Cleanup: Terminating process {pid} on port {port}...")
                
                # Kill children first (recursive)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # Kill the parent
                parent.kill()
                parent.wait(timeout=2)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process already vanished or we don't have permission (likely system proc)
                pass
            except psutil.TimeoutExpired:
                pass

        # 3. Final Verification: Wait a beat and check the port one last time
        time.sleep(0.5)
        if is_port_in_use(port):
            logger.error(f"🚨 CRITICAL: Failed to clear port {port}. A process is still holding it!")
            return False
        
        return True

    except Exception as e:
        logger.debug(f"Cleanup trace for port {port}: {e}")
        return not is_port_in_use(port)
