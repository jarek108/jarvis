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
    
    if not soft:
        logger.warning("Performng strict global purge...")
        kill_all_jarvis_services()
        time.sleep(1)
        baseline_vram = get_gpu_vram_usage()
        logger.info(f"📉 Baseline VRAM: {baseline_vram:.1f} GB")

    python_exe = resolve_path(cfg['paths']['venv_python'])
    stt_script = os.path.join(project_root, "servers", "stt_server.py")
    tts_script = os.path.join(project_root, "servers", "tts_server.py")
    
    active_services = []

    for svc in target.get('services', []):
        sid = svc['id']
        engine = svc['engine']
        params = svc.get('params', {})
        
        logger.info(f"⚙️ Setting up service: {sid} ({engine})")
        
        if engine == "ollama":
            port = cfg['ports']['ollama']
            if not wait_for_port(port, timeout=1):
                logger.info(f"🚀 Starting Ollama...")
                os.environ['OLLAMA_MODELS'] = get_ollama_models()
                start_server(["ollama", "serve"], loud=loud)
                wait_for_port(port)
            active_services.append({"id": sid, "engine": engine, "port": port, "params": params})

        elif engine == "vllm":
            port = cfg['ports'].get('vllm', 8300)
            total_vram = get_gpu_total_vram()
            
            # Smart Allocator
            num_ctx = params.get('num_ctx') or params.get('max_model_len') or 16384
            base_gb, cost_10k = get_model_calibration(sid, engine="vllm")
            
            if base_gb is not None:
                required_gb = base_gb + ((num_ctx / 10000.0) * cost_10k)
                vllm_util = (required_gb / total_vram) + 0.05
                logger.info(f"🧠 SmartAllocator: {sid} needs {required_gb:.2f}GB for {num_ctx} ctx. Util: {vllm_util:.3f}")
            else:
                vllm_util = params.get('gpu_memory_utilization', 0.4)
                logger.warning(f"⚠️ No calibration for {sid}. Using default util: {vllm_util}")

            vllm_util = min(0.95, max(0.1, vllm_util))
            
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
                "--model", sid,
                "--gpu-memory-utilization", str(round(vllm_util, 3)),
                "--max-model-len", str(num_ctx)
            ]
            subprocess.run(cmd, capture_output=True)
            wait_for_port(port, timeout=300)
            active_services.append({"id": sid, "engine": engine, "port": port, "params": params})

        elif engine == "native":
            # Determine if STT or TTS
            if "whisper" in sid.lower():
                port = cfg['stt_loadout'].get(sid)
                if not port: logger.error(f"No port mapping for STT: {sid}"); continue
                
                logger.info(f"🚀 Starting STT Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, stt_script, "--port", str(port), "--model", sid]
                # Add params as flags
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud)
                wait_for_port(port)
                active_services.append({"id": sid, "engine": engine, "port": port, "params": params})
                
            elif "chatterbox" in sid.lower():
                # Extract variant (chatterbox-multilingual -> multilingual)
                variant = sid.replace("chatterbox-", "")
                port = cfg['tts_loadout'].get(sid) or cfg['tts_loadout'].get(variant)
                if not port: logger.error(f"No port mapping for TTS: {sid}"); continue
                
                logger.info(f"🚀 Starting TTS Server [{sid}]...")
                os.environ['HF_HOME'] = get_hf_home()
                cmd = [python_exe, tts_script, "--port", str(port), "--variant", variant]
                for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
                start_server(cmd, loud=loud)
                wait_for_port(port, timeout=120)
                active_services.append({"id": sid, "engine": engine, "port": port, "params": params})

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
