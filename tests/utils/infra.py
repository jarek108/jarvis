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

def start_server(cmd, loud=False):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    final_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd]) if isinstance(cmd, list) else cmd
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return subprocess.Popen(final_cmd, creationflags=flags, shell=True, cwd=project_root)

def wait_for_port(port: int, timeout: int = 120, process=None) -> bool:
    # Local import to avoid circular dependency if get_service_status moves elsewhere
    from .vram import get_service_status
    start_time = time.time()
    while time.time() - start_time < timeout:
        status, info = get_service_status(port)
        if status == "ON": return True
        if process and process.poll() is not None: return False
        time.sleep(1)
    return False

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

def is_vllm_docker_running():
    try:
        res = subprocess.run(["docker", "ps", "--filter", "name=vllm-server", "--format", "{{.Names}}"], capture_output=True, text=True)
        return "vllm-server" in res.stdout
    except: return False

def kill_process_on_port(port: int):
    try:
        cfg = load_config()
        if port == cfg['ports']['ollama'] and os.name == 'nt':
            os.system("taskkill /F /IM ollama* /T > nul 2>&1")
            time.sleep(0.5)
        
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
    ports.update(cfg['stt_loadout'].values())
    ports.update(cfg['tts_loadout'].values())
    return ports

def kill_all_jarvis_services():
    """Kills every service defined in config.yaml."""
    ports = get_jarvis_ports()
    for port in ports:
        kill_process_on_port(port)
