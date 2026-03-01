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
    get_hf_home, get_ollama_models, get_model_calibration, get_gpu_total_vram
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

def save_runtime_registry(services, project_root):
    registry_path = os.path.join(project_root, "model_calibrations", "runtime_registry.json")
    data = {
        "active_loadout": services,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(registry_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"📝 Runtime registry updated at {registry_path}")

def apply_loadout(name, loud=False, soft=False):
    cfg = load_config()
    project_root = os.getcwd()
    loadout_path = os.path.join(project_root, "loadouts", f"{name}.yaml")
    
    if not os.path.exists(loadout_path):
        logger.error(f"Loadout '{name}' not found at {loadout_path}")
        return

    with open(loadout_path, "r") as f:
        target = yaml.safe_load(f)

    logger.info(f"Applying Loadout: {target.get('description', name)}")
    
    # 1. Initialize Session Directory
    session_id = f"RUN_{time.strftime('%Y%m%d_%H%M%S')}"
    session_dir = os.path.join(project_root, "logs", "sessions", session_id)
    os.makedirs(session_dir, exist_ok=True)
    logger.info(f"📁 Initialized Loadout Session: {session_id}")

    # 2. Pre-calculate active_services with ports and per-model session logs
    active_services = []
    for svc in target.get('services', []):
        sid = svc['id']
        engine = svc['engine']
        params = svc.get('params', {})
        
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
            log_path = os.path.join(session_dir, f"svc_{stype}_{sid.replace(':', '-').replace('/', '--')}.log")
            active_services.append({
                "id": sid, "engine": engine, "port": port, 
                "params": params, "log_path": log_path, "type": stype
            })
    
    save_runtime_registry(active_services, project_root)

    # 3. Surgical Purge
    if not soft:
        logger.warning("Performing strict global purge...")
        kill_all_jarvis_services()
        time.sleep(1)
        baseline_vram = get_gpu_vram_usage()
        logger.info(f"📉 Baseline VRAM: {baseline_vram:.1f} GB")
    else:
        logger.info("Soft switch: Purging only replaced service types...")
        stt_ports = list(cfg['stt_loadout'].values())
        tts_ports = list(cfg['tts_loadout'].values())
        vllm_port = cfg['ports'].get('vllm')
        from utils.infra import kill_jarvis_ports
        kill_jarvis_ports(stt_ports + tts_ports + ([vllm_port] if vllm_port else []))

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
        
        logger.info(f"⚙️ Setting up service: {sid} ({engine})")
        
        # Initialize Log with Physics Header
        with open(log_path, "w", encoding="utf-8") as f_head:
            f_head.write(f"[Lifecycle] Service: {sid}\n")
            f_head.write(f"[Lifecycle] Engine: {engine}\n")
            f_head.write(f"[Lifecycle] Port: {port}\n")
            f_head.write(f"[Lifecycle] Params: {params}\n")
            
            if engine == "vllm":
                total_vram = get_gpu_total_vram()
                base_gb, cost_10k = get_model_calibration(sid, engine="vllm")
                num_ctx = params.get('num_ctx') or params.get('max_model_len') or 16384
                if base_gb is not None:
                    required_gb = base_gb + ((num_ctx / 10000.0) * cost_10k)
                    vllm_util = (required_gb / total_vram) + 0.05
                    svc['required_gb'] = round(required_gb, 2)
                    f_head.write(f"[Lifecycle] SmartAllocator: {base_gb}GB base + {num_ctx} ctx. Required: {svc['required_gb']}GB. Util: {round(vllm_util, 3)}\n")
                else:
                    vllm_util = params.get('gpu_memory_utilization', 0.4)
                    svc['required_gb'] = round(vllm_util * total_vram, 2)
                    f_head.write(f"[Lifecycle] WARNING: No calibration found. Using default util: {vllm_util}\n")
                f_head.write("-" * 40 + "\n\n")

        if engine == "ollama":
            if not wait_for_port(port, timeout=1):
                logger.info(f"🚀 Starting Ollama...")
                os.environ['OLLAMA_MODELS'] = get_ollama_models()
                # Redirect Ollama output to its session log
                log_file = open(log_path, "a", encoding="utf-8")
                start_server(["ollama", "serve"], loud=loud, log_file=log_file)
                wait_for_port(port)

        elif engine == "vllm":
            from utils.config import resolve_canonical_id
            canonical_id = resolve_canonical_id(sid, engine="vllm")
            num_ctx = params.get('num_ctx') or params.get('max_model_len') or 16384
            
            if is_vllm_docker_running():
                stop_vllm_docker()
            
            logger.info(f"🚀 Starting vLLM Docker [{sid}]...")
            hf_cache = get_hf_home()
            cmd = [
                "docker", "run", "--gpus", "all", "-d", 
                "--name", "vllm-server",
                "-p", f"{port}:8000",
                "-v", f"{hf_cache}:/root/.cache/huggingface",
                "vllm/vllm-openai",
                "--model", canonical_id,
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
                logger.info(f"🚀 Starting STT Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, stt_script, "--port", str(port), "--model", sid]
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud, log_file=log_file)
                wait_for_port(port)
                
            elif "chatterbox" in sid.lower():
                variant = sid.replace("chatterbox-", "")
                logger.info(f"🚀 Starting TTS Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, tts_script, "--port", str(port), "--variant", variant]
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud, log_file=log_file)
                wait_for_port(port, timeout=120)

    # Final registry save to capture required_gb
    save_runtime_registry(active_services, project_root)


def kill_loadout(target):
    cfg = load_config()
    if target == "all":
        kill_all_jarvis_services()
        # Clear registry
        registry_path = os.path.join(os.getcwd(), "model_calibrations", "runtime_registry.json")
        if os.path.exists(registry_path): os.remove(registry_path)
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
