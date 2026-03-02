import os
import subprocess
import psutil
import time
from ..config import load_config, resolve_path
from .ports import is_port_in_use, get_jarvis_ports
from .status import get_service_status
from .docker import stop_vllm_docker

def start_server(cmd, loud=False, log_file=None):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
