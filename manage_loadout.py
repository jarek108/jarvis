import os
import sys
import yaml
import time
import json
import psutil
import subprocess
import shutil
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from utils import load_config
from utils.edge import vram

def get_runtime_registry_path(project_root=None):
    if not project_root: project_root = script_dir
    return os.path.join(project_root, "system_config", "model_calibrations", "runtime_registry.json")

def save_runtime_registry(services, project_root=None, external_vram=0.0, loadout_id="NONE"):
    """
    Saves the list of currently active model services and their ports.
    Used by the UI to detect which models are 'live' for binding.
    """
    registry_path = get_runtime_registry_path(project_root)
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    
    data = {
        "timestamp": time.time(),
        "loadout": loadout_id,
        "external": external_vram,
        "models": services # List of {id, engine, port, log_path}
    }
    with open(registry_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Runtime registry updated at {registry_path}")

def apply_loadout(name, project_root=None, soft=False, external_vram=0.0):
    if not project_root: project_root = script_dir
    loadouts_file = os.path.join(project_root, "system_config", "loadouts.yaml")
    
    if not os.path.exists(loadouts_file):
        logger.error(f"Loadouts file not found: {loadouts_file}")
        return

    with open(loadouts_file, "r") as f:
        all_loadouts = yaml.safe_load(f)
    
    target = all_loadouts.get(name)
    if not target:
        logger.error(f"Loadout '{name}' not found in loadouts.yaml")
        return

    description = target.get('description', name)
    models = target.get('models', []) if isinstance(target, dict) else target
    
    logger.info(f"Applying Loadout: {description}")
    
    # Initialize session for logs
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_id = f"RUN_{timestamp}"
    session_dir = os.path.join(project_root, "logs", "sessions", session_id)
    os.makedirs(session_dir, exist_ok=True)
    logger.info(f"Initialized Loadout Session: {session_id}")

    from utils.config import parse_model_string
    registry_entries = []
    
    # 1. Identify what needs to be killed vs kept
    required_services = []
    for m_str in models:
        m_data = parse_model_string(m_str)
        if m_data: required_services.append(m_data)

    required_ids = [s['id'] for s in required_services]
    
    # 2. Strategic Purge
    if not soft:
        logger.warning("Performing strict global purge...")
        kill_loadout("all", project_root)
    else:
        # Check current VRAM usage before starting
        logger.info(f"System External VRAM: {external_vram:.1f} GB")
        
        logger.info("Soft switch: Purging only replaced service types...")
        # Get list of running services (if we can find them)
        # For now, let's just kill the specific IDs we are about to launch to be safe
        for s in required_services:
            kill_service(s['id'], project_root)

    # 3. Launching
    config = load_config()
    is_ui_test = os.environ.get('JARVIS_UI_TEST') == "1"
    
    # Pre-check health for smart reuse
    from utils.infra.status import get_system_health
    all_ports = []
    for s_data in required_services:
        sid = s_data['id']
        engine = s_data['engine']
        role = "stt" if "whisper" in sid.lower() else "tts" if "chatterbox" in sid.lower() or "piper" in sid.lower() else "llm"
        port = config.get(f"{role}_loadout", {}).get(sid) or config.get("ports", {}).get(engine)
        if port: all_ports.append(port)
    
    current_health = get_system_health(ports=all_ports)

    for s_data in required_services:
        sid = s_data['id']
        engine = s_data['engine']
        params = s_data['params']
        
        # Determine logical type
        role = "stt" if "whisper" in sid.lower() else "tts" if "chatterbox" in sid.lower() or "piper" in sid.lower() else "llm"
        port = config.get(f"{role}_loadout", {}).get(sid)
        
        if not port:
            # Check general ports
            port = config.get("ports", {}).get(engine)
            
        if not port:
            logger.error(f"Could not determine port for {sid}. Skipping.")
            continue

        # SMART REUSE: If service is already ON/BUSY on this port, skip launch
        if port in current_health and current_health[port]['status'] in ["ON", "BUSY"]:
            logger.info(f"Service {sid} already active on port {port}. Reusing.")
            registry_entries.append({
                "id": sid,
                "engine": engine,
                "port": port,
                "role": role,
                "log_path": os.path.join(session_dir, f"svc_{role}_{sid.replace('/', '--').replace(':', '--')}.log")
            })
            continue

        logger.info(f"Setting up service: {sid} ({engine})")
        safe_sid = sid.replace("/", "--").replace(":", "--")
        log_file = os.path.join(session_dir, f"svc_{role}_{safe_sid}.log")
        
        if is_ui_test:
            # Spawn a lightweight stub server for UI/Mock testing
            venv_python = config.get('paths', {}).get('venv_python', 'python')
            stub_script = os.path.join(project_root, "tests", "test_utils", "stubs.py")
            cmd = [venv_python, stub_script, "--port", str(port)]
            logger.info(f"Starting MOCK Server [{sid}] on port {port}...")
            
            lf = open(log_file, "w")
            subprocess.Popen(cmd, stdout=lf, stderr=lf, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        elif engine == "ollama":
            # Ollama is usually a persistent background service
            # We just need to make sure the model is pulled and serve is ready
            try:
                # Check if ollama is running
                subprocess.run(["ollama", "list"], capture_output=True, check=True)
            except:
                logger.info(f"Starting Ollama...")
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
                time.sleep(2)
            
            # Trigger model pull (async)
            subprocess.Popen(["ollama", "run", sid, ""], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        elif engine == "vllm":
            # vLLM requires Docker
            docker_cmd = ["docker", "ps"]
            try:
                subprocess.run(docker_cmd, capture_output=True, check=True)
            except:
                logger.error(f"Docker daemon is down. Skipping vLLM: {sid}")
                continue

            # Check for physical calibration
            v_cfg = config.get('vllm', {})
            safety_buf = v_cfg.get('vram_safety_buffer', 0.1)
            static_floor = v_cfg.get('vram_static_floor', 1.0)
            
            # Simplified VRAM calc for this helper
            # (In a real scenario, this would use physics.db)
            total_gpu_vram = vram.get_gpu_total_vram()
            available = total_gpu_vram - external_vram
            
            # Limit vLLM to a safe portion of available VRAM
            gpu_fraction = max(0.4, (available - static_floor) / total_gpu_vram)
            gpu_fraction = min(0.95, gpu_fraction - safety_buf)

            logger.info(f"Starting vLLM Docker [{sid}]...")
            vllm_cmd = [
                "docker", "run", "--gpus", "all", "-d", "--rm",
                "--name", f"jarvis-{sid}",
                "-p", f"{port}:8000",
                "-e", f"HF_HOME={os.environ.get('HF_HOME', '/root/.cache/huggingface')}",
                "-v", f"{os.environ.get('HF_HOME')}:/root/.cache/huggingface",
                "vllm/vllm-openai:latest",
                "--model", sid,
                "--gpu-memory-utilization", f"{gpu_fraction:.2f}",
                "--max-model-len", str(v_cfg.get('default_context_size', 8192))
            ]
            subprocess.run(vllm_cmd, check=True)

        elif engine == "native":
            # Native Python Servers (STT/TTS)
            venv_python = config.get('paths', {}).get('venv_python', 'python')
            server_script = "servers/stt_server.py" if role == "stt" else "servers/tts_server.py"
            
            cmd = [
                venv_python, server_script,
                "--model", sid,
                "--port", str(port)
            ]
            
            logger.info(f"Starting STT Server [{sid}]...") if role == "stt" else logger.info(f"Starting TTS Server [{sid}]...")
            
            with open(log_file, "w") as lf:
                subprocess.Popen(cmd, stdout=lf, stderr=lf, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)

        registry_entries.append({
            "id": sid,
            "engine": engine,
            "port": port,
            "role": role,
            "log_path": log_file
        })

    # 4. Final Registry Sync
    save_runtime_registry(registry_entries, project_root, external_vram=external_vram, loadout_id=name)

def kill_loadout(name, project_root=None):
    """Kills all Jarvis-managed Docker containers and Python server processes."""
    if name == "all":
        is_mock = os.environ.get('JARVIS_MOCK_ALL') == "1"
        from utils import load_config
        cfg = load_config()
        
        # 1. Port-First Kill (Fast) - Target only our known ports
        import psutil
        jarvis_ports = set()
        jarvis_ports.update(cfg.get('stt_loadout', {}).values())
        jarvis_ports.update(cfg.get('tts_loadout', {}).values())
        jarvis_ports.update(cfg.get('ports', {}).values())
        
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port in jarvis_ports and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        cmd = " ".join(proc.cmdline()).lower()
                        # Safety check: Only kill if it looks like a Jarvis component or engine
                        if any(x in cmd for x in ["stubs.py", "stt_server.py", "tts_server.py", "ollama", "vllm", "python"]):
                            if "jarvis_daemon.py" not in cmd and "runner.py" not in cmd:
                                for child in proc.children(recursive=True):
                                    try: child.kill()
                                    except: pass
                                proc.kill()
                                logger.info(f"Killed orphan on port {conn.laddr.port}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        except Exception as e:
            logger.warning(f"Port-first cleanup had issues: {e}")

        if not is_mock:
            # 2. Docker (Only kill Docker in real environments)
            try:
                res = subprocess.run(["docker", "ps", "--filter", "name=jarvis-", "--format", "{{.Names}}"], capture_output=True, text=True)
                for container in res.stdout.split():
                    subprocess.run(["docker", "stop", container])
            except: pass
            
    # 3. Registry Reset
    save_runtime_registry([], project_root, loadout_id="NONE")

def restart_service(sid, loadout_id, project_root=None):
    """Restarts a specific service by name."""
    kill_service(sid, project_root)
    # Re-apply only this service from the current loadout (simplified)
    # In a full impl, we'd look up the exact model string for this ID
    logger.info(f"Service {sid} restart requested. (Stub Implementation)")

def kill_service(sid, project_root=None):
    """Surgically kill a specific model service by identifying the process on its port."""
    from utils import load_config
    cfg = load_config()
    
    # 1. Map SID to Port
    port = None
    for role in ['stt_loadout', 'tts_loadout']:
        if sid in cfg.get(role, {}):
            port = cfg[role][sid]
            break
    if not port and sid in cfg.get('ports', {}):
        port = cfg['ports'][sid]
    
    # 2. Port-First Kill (Fast)
    if port:
        import psutil
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.pid:
                try:
                    proc = psutil.Process(conn.pid)
                    # Verify it's actually a Jarvis service before killing
                    cmd = " ".join(proc.cmdline()).lower()
                    if any(x in cmd for x in ["stubs.py", "stt_server.py", "tts_server.py", "ollama", "vllm"]):
                        for child in proc.children(recursive=True):
                            try: child.kill()
                            except: pass
                        proc.kill()
                        logger.info(f"Surgically killed {sid} on port {port}")
                except (psutil.NoSuchProcess, psutil.AccessDenied): pass

    # 3. Docker Fallback (Fast)
    subprocess.run(["docker", "stop", f"jarvis-{sid}"], capture_output=True)
    logger.info(f"Cleanup finished for service: {sid}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=str)
    parser.add_argument("--kill", type=str)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.apply:
        apply_loadout(args.apply)
    elif args.kill:
        kill_loadout(args.kill)
