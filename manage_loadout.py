"""
[Title] : Jarvis Loadout Manager
[Section] : Description
This script manages the persistent inference cluster for the Jarvis Assistant.
It allows you to view the current system state, apply model presets (loadouts),
and perform clean sweeps of the GPU infrastructure.
"""

import os
import sys
import argparse
import subprocess
import yaml
import time
import json
from loguru import logger

from utils import (
    get_system_health, load_config, kill_process_on_port, wait_for_port, 
    start_server, is_vllm_docker_running, stop_vllm_docker, 
    kill_all_jarvis_services, get_gpu_vram_usage, resolve_path,
    get_hf_home, get_ollama_models, get_model_calibration, get_gpu_total_vram,
    get_project_root, log_msg
)
from utils.console import GREEN, RED, YELLOW, GRAY, RESET, BOLD, CYAN

def print_status():
    health = get_system_health()
    LINE_LEN = 120
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{'JARVIS INFERENCE CLUSTER STATUS':^120}{RESET}")
    print("="*LINE_LEN)
    print(f"{'Service':<30} | {'Port':<8} | {'Status':<15} | {'Details'}")
    print("-" * LINE_LEN)
    
    for port, info in health.items():
        if info['type'] == "broker": continue # Hide orchestrator from model cluster
        status = info['status']
        name = info['label']
        detail_val = info['info']
        
        color = GRAY
        if status == "ON": color = GREEN
        elif status == "UNHEALTHY": color = RED
        elif status == "BUSY": color = YELLOW
        
        details = detail_val or ""
        print(f"{name:<30} | {port:<8} | {color}{status:<15}{RESET} | {details}")
    
    print("="*LINE_LEN + "\n")

def save_runtime_registry(services, project_root=None, external_vram=None, loadout_id=None):
    root = project_root if project_root else get_project_root()
    registry_path = os.path.join(root, "system_config", "model_calibrations", "runtime_registry.json")
    
    # Preserve existing external and loadout_id if not provided
    current_external = 0.0
    current_loadout_id = "NONE"
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r") as f:
                reg_data = json.load(f)
                current_external = reg_data.get("system_external_vram", 0.0)
                current_loadout_id = reg_data.get("loadout_id", "NONE")
        except: pass

    data = {
        "active_loadout": services,
        "loadout_id": loadout_id if loadout_id is not None else current_loadout_id,
        "system_external_vram": external_vram if external_vram is not None else current_external,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log_msg(f"Runtime registry updated at {registry_path}")

def apply_loadout(name, loud=False, soft=False):
    cfg = load_config()
    project_root = get_project_root()
    loadouts_file = os.path.join(project_root, "system_config", "loadouts.yaml")
    
    if not os.path.exists(loadouts_file):
        log_msg(f"Loadouts file not found: {loadouts_file}", level="error")
        return

    with open(loadouts_file, "r") as f:
        all_loadouts = yaml.safe_load(f)

    if name not in all_loadouts:
        log_msg(f"Loadout '{name}' not found in loadouts.yaml", level="error")
        return

    target = all_loadouts[name]
    # 'target' can be a list of strings OR a dict with a 'models' key
    model_strings = target.get('models', []) if isinstance(target, dict) else target
    description = target.get('desc', name) if isinstance(target, dict) else name

    log_msg(f"Applying Loadout: {description}")
    
    # 1. Initialize Session Directory
    session_id = f"RUN_{time.strftime('%Y%m%d_%H%M%S')}"
    session_dir = os.path.join(project_root, "logs", "sessions", session_id)
    os.makedirs(session_dir, exist_ok=True)
    log_msg(f"Initialized Loadout Session: {session_id}")
    
    # 1.1 Perform Log Cleanup
    from utils import cleanup_old_logs
    cleanup_old_logs()
    print() # SEPARATION

    # 2. Pre-calculate active_services with ports and per-model session logs
    from utils.config import parse_model_string
    active_services = []
    
    for m_str in model_strings:
        svc_data = parse_model_string(m_str)
        if not svc_data: continue
        
        sid = svc_data['id']
        engine = svc_data['engine']
        params = svc_data['params']
        
        # Resolve ports and logs
        stype = "llm"
        if engine == "native":
            stype = "stt" if "whisper" in sid.lower() else "tts"
            
        if engine == "ollama": port = cfg['ports']['ollama']
        elif engine == "vllm": port = cfg['ports'].get('vllm', 8300)
        elif engine == "native":
            if stype == "stt": port = cfg['stt_loadout'].get(sid)
            else:
                variant = sid.replace("chatterbox-", "")
                port = cfg['tts_loadout'].get(sid) or cfg['tts_loadout'].get(variant)
        else: port = None
        
        if port:
            from utils.config import safe_filename
            safe_sid = safe_filename(sid)
            log_path = os.path.join(session_dir, f"svc_{stype}_{safe_sid}.log")
            svc_entry = {
                "id": sid, "engine": engine, "port": port, 
                "params": params, "log_path": log_path, "type": stype
            }
            
            # Pre-calculate required GB for all engines
            total_vram = get_gpu_total_vram()
            base_gb, cost_10k = get_model_calibration(sid, engine=engine)
            
            if base_gb is not None:
                # Calculate based on params or defaults
                if engine in ["vllm", "ollama"]:
                    num_ctx = params.get('num_ctx') or params.get('max_model_len') or 8192
                    svc_entry['required_gb'] = round(base_gb + ((num_ctx / 10000.0) * (cost_10k or 0)), 2)
                else:
                    svc_entry['required_gb'] = round(base_gb, 2)
            else:
                # Fallback for uncalibrated models
                if engine == "vllm":
                    vllm_util = params.get('gpu_memory_utilization', 0.4)
                    svc_entry['required_gb'] = round(vllm_util * total_vram, 2)
                elif engine == "native":
                    # Heuristic for Whisper
                    if "tiny" in sid: svc_entry['required_gb'] = 0.5
                    elif "base" in sid: svc_entry['required_gb'] = 1.0
                    elif "large" in sid: svc_entry['required_gb'] = 3.5

            active_services.append(svc_entry)
    
    # 3. Surgical Purge and External Capture
    external_vram = None
    if not soft:
        log_msg("Performing strict global purge...", level="warning")
        kill_all_jarvis_services()
        time.sleep(1.5)
        external_vram = get_gpu_vram_usage()
        log_msg(f"System External VRAM: {external_vram:.1f} GB")
    else:
        log_msg("Soft switch: Purging only replaced service types...")
        stt_ports = list(cfg['stt_loadout'].values())
        tts_ports = list(cfg['tts_loadout'].values())
        vllm_port = cfg['ports'].get('vllm')
        from utils.infra import kill_jarvis_ports
        kill_jarvis_ports(stt_ports + tts_ports + ([vllm_port] if vllm_port else []))

    # Save registry IMMEDIATELY so UI shows "STARTUP" for all models
    save_runtime_registry(active_services, project_root, external_vram=external_vram, loadout_id=name)
    print() # SEPARATION

    # 4. Service Startup with Lifecycle Headers
    python_exe = resolve_path(cfg['paths']['venv_python'])
    stt_script = os.path.join(project_root, "servers", "stt_server.py")
    tts_script = os.path.join(project_root, "servers", "tts_server.py")

    for svc in active_services:
        sid = svc['id']
        engine = svc['engine']
        port = svc['port']
        params = svc['params']
        log_path = svc['log_path']
        
        log_msg(f"Setting up service: {sid} ({engine})")
        
        # Initialize Log with Physics Header
        with open(log_path, "w", encoding="utf-8") as f_head:
            f_head.write(f"[Lifecycle] Service: {sid}\n")
            f_head.write(f"[Lifecycle] Engine: {engine}\n")
            f_head.write(f"[Lifecycle] Port: {port}\n")
            f_head.write(f"[Lifecycle] Params: {params}\n")
            if 'required_gb' in svc:
                f_head.write(f"[Lifecycle] SmartAllocator: Required VRAM: {svc['required_gb']} GB\n")
            f_head.write("-" * 40 + "\n\n")

        if engine == "ollama":
            if not wait_for_port(port, timeout=1):
                log_msg(f"Starting Ollama...")
                os.environ['OLLAMA_MODELS'] = get_ollama_models()
                # Redirect Ollama output to its session log
                log_file = open(log_path, "a", encoding="utf-8")
                start_server(["ollama", "serve"], loud=loud, log_file=log_file)
                wait_for_port(port)

        elif engine == "vllm":
            num_ctx = params.get('num_ctx') or params.get('max_model_len') or 16384
            
            # Verify Docker Daemon
            from utils.infra import is_docker_daemon_running
            if not is_docker_daemon_running():
                with open(log_path, "a", encoding="utf-8") as f_err:
                    f_err.write("ERROR: Docker daemon is not running. Cannot start vLLM.\n")
                log_msg(f"Docker daemon is down. Skipping vLLM: {sid}", level="error")
                continue

            # Calculate utilization for docker command
            total_vram = get_gpu_total_vram()
            if 'required_gb' in svc:
                # Dynamically restrict utilization to avoid OOM when massive models run alongside STT/TTS
                # 'external_vram' was captured after purge, BUT other services in THIS loadout might have just started!
                # We need to compute the max safe utilization based on the remaining physical memory.
                
                other_services_vram = sum(s.get('required_gb', 2.0) for s in active_services if s['id'] != sid)
                system_buffer = (external_vram if external_vram is not None else 2.0) + 1.0
                
                max_safe_vram = max(0, total_vram - (other_services_vram + system_buffer))
                allocated_vram = min(svc['required_gb'], max_safe_vram)
                vllm_util = allocated_vram / total_vram
            else:
                vllm_util = params.get('gpu_memory_utilization', 0.4)
            
            # For massive models like 30B, ensure we don't accidentally ask for 95% if other things are running
            vllm_util = min(0.85, max(0.1, vllm_util))

            if is_vllm_docker_running():
                stop_vllm_docker()
            
            log_msg(f"Starting vLLM Docker [{sid}]...")
            hf_cache = get_hf_home()
            cmd = [
                "docker", "run", "--gpus", "all", "-d", 
                "--name", "vllm-server",
                "-p", f"{port}:8000",
                "-v", f"{hf_cache}:/root/.cache/huggingface",
                "vllm/vllm-openai",
                "--model", sid,
                "--gpu-memory-utilization", str(round(vllm_util, 3)),
                "--max-model-len", str(num_ctx)
            ]
            subprocess.run(cmd, capture_output=True)
            
            # PIPE DOCKER LOGS TO FILE IN BACKGROUND
            log_file = open(log_path, "a", encoding="utf-8")
            subprocess.Popen(
                ["docker", "logs", "-f", "vllm-server"], 
                stdout=log_file, stderr=log_file, 
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
            wait_for_port(port, timeout=300)

        elif engine == "native":
            log_file = open(log_path, "a", encoding="utf-8")
            if "whisper" in sid.lower():
                log_msg(f"Starting STT Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, stt_script, "--port", str(port), "--model", sid]
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud, log_file=log_file)
                wait_for_port(port)
                
            elif "chatterbox" in sid.lower():
                variant = sid.replace("chatterbox-", "")
                log_msg(f"Starting TTS Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, tts_script, "--port", str(port), "--variant", variant]
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud, log_file=log_file)
                wait_for_port(port, timeout=120)
    print() # SEPARATION



def kill_service(sid):
    """Surgically kills a service and removes it from the registry."""
    cfg = load_config()
    project_root = get_project_root()
    registry_path = os.path.join(root, "system_config", "model_calibrations", "runtime_registry.json")
    
    if not os.path.exists(registry_path): return
    
    with open(registry_path, "r") as f:
        data = json.load(f)
        active = data.get("active_loadout", [])
    
    svc = next((s for s in active if s['id'] == sid), None)
    if not svc: return

    logger.warning(f"Surgical Kill: {sid} on port {svc['port']}")
    kill_process_on_port(svc['port'])
    
    # Update registry
    new_active = [s for s in active if s['id'] != sid]
    save_runtime_registry(new_active, project_root)

def restart_service(sid, loadout_name):
    """Kills a service and restarts it using its definition from the specified loadout."""
    kill_service(sid)
    # Give OS a moment to release port
    time.sleep(1)
    apply_loadout(loadout_name, soft=True)

def kill_loadout(target):
    cfg = load_config()
    if target == "all":
        kill_all_jarvis_services()
        time.sleep(1.0)
        external = get_gpu_vram_usage()
        # Save an empty registry with the new external baseline
        save_runtime_registry([], external_vram=external)
        logger.info(f"🗑️ Cleared runtime registry. External VRAM: {external:.1f} GB")
    else:
        # Simple port-based kill for now
        logger.warning(f"Targeted kill for '{target}' not yet updated for Loadout 2.0. Use 'all'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Loadout Manager 2.0")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--apply", type=str)
    parser.add_argument("--soft", action="store_true")
    parser.add_argument("--kill", type=str)
    parser.add_argument("--loud", action="store_true")
    
    args = parser.parse_args()
    if args.status: print_status()
    elif args.apply: apply_loadout(args.apply, loud=args.loud, soft=args.soft)
    elif args.kill: kill_loadout(args.kill)
    else: parser.print_help()
