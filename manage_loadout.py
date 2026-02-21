"""
[Title] : Jarvis Loadout Manager
[Section] : Description
This script manages the persistent inference cluster for the Jarvis Assistant.
It allows you to view the current system state, apply model presets (loadouts),
and perform clean sweeps of the GPU infrastructure. Servers are started in
headless mode by default to prevent console window clutter.

[Section] : Usage Examples
[Subsection] : View Cluster Health
python manage_loadout.py --status

[Subsection] : Apply a Preset Loadout (Strict Reset)
Kills all existing services, measures baseline VRAM, then starts the loadout.
python manage_loadout.py --apply base-qwen30-multi

[Subsection] : Apply a Loadout Layer (Soft Start)
Starts only missing services without killing anything. Useful for adding TTS to an running LLM.
python manage_loadout.py --apply tiny-gpt20-turbo --soft

[Subsection] : Kill a Specific Service
python manage_loadout.py --kill faster-whisper-tiny
python manage_loadout.py --kill all

[Subsection] : Debug Mode
Show console windows for newly started servers.
python manage_loadout.py --apply vanilla_fast --loud

[Section] : Resources
- Loadout Definitions: tests/loadouts/*.yaml
"""

import os
import sys
import argparse
import subprocess
import yaml
import time
from loguru import logger

from utils import (
    get_system_health, load_config, kill_process_on_port, wait_for_port, 
    start_server, is_vllm_docker_running, stop_vllm_docker, 
    kill_all_jarvis_services, get_gpu_vram_usage, resolve_path,
    get_hf_home, get_ollama_models
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
        if name == "LLM" and status == "ON":
            details = f"{BOLD}Ollama Resident:{RESET} {detail_val}"
            
        print(f"{name:<30} | {port:<8} | {color}{status:<15}{RESET} | {details}")
    
    print("="*LINE_LEN + "\n")

def apply_loadout(name, loud=False, soft=False):
    cfg = load_config()
    loadout_path = os.path.join(os.getcwd(), "loadouts", f"{name}.yaml")
    if not os.path.exists(loadout_path):
        loadout_path = os.path.join(os.getcwd(), "loadouts", f"{name}")
        if not os.path.exists(loadout_path):
            logger.error(f"Loadout '{name}' not found.")
            return

    with open(loadout_path, "r") as f:
        target = yaml.safe_load(f)

    logger.info(f"Applying Loadout: {target.get('description', name)}")
    
    # 1. Strict Purge & Baseline Measurement
    if not soft:
        logger.warning("🧹 Performing strict global purge...")
        kill_all_jarvis_services()
        baseline_vram = get_gpu_vram_usage()
        logger.info(f"📉 Baseline VRAM: {baseline_vram:.1f} GB")
    else:
        logger.info("ℹ️ Soft mode enabled: Skipping purge.")

    python_exe = resolve_path(cfg['paths']['venv_python'])
    stt_script = os.path.join(os.getcwd(), "servers", "stt_server.py")
    tts_script = os.path.join(os.getcwd(), "servers", "tts_server.py")

    # 2. Start LLM Engine if needed
    llm_config = target.get('llm')
    if llm_config:
        engine = "ollama"
        model = llm_config
        if isinstance(llm_config, dict):
            engine = llm_config.get("engine", "ollama")
            model = llm_config.get("model")
        elif isinstance(llm_config, str) and llm_config.startswith("vllm:"):
            engine = "vllm"
            model = llm_config[5:]

        if engine == "ollama":
            llm_port = cfg['ports']['ollama']
            if not os.system(f"netstat -ano | findstr :{llm_port} > nul"):
                logger.info("ℹ️ Ollama already running.")
            else:
                logger.info("🚀 Starting Ollama...")
                # Broadcast OLLAMA_MODELS to native process
                os.environ['OLLAMA_MODELS'] = get_ollama_models()
                start_server(["ollama", "serve"], loud=loud)
                wait_for_port(llm_port)
        elif engine == "vllm":
            vllm_port = cfg['ports'].get('vllm', 8300)
            
            # --- START SMART ALLOCATOR ---
            from utils import get_gpu_total_vram, get_model_calibration
            total_vram = get_gpu_total_vram()
            
            # Resolve Context Size
            default_ctx = cfg.get('vllm', {}).get('default_context_size', 16384)
            
            # Try to load physics
            base_gb, cost_10k = get_model_calibration(model, engine="vllm")
            
            if base_gb:
                # Formula: Required = Base + (Ctx / 10000 * Cost)
                required_gb = base_gb + ((default_ctx / 10000.0) * cost_10k)
                vllm_util = (required_gb / total_vram) + 0.05
                logger.info(f"🧠 SmartAllocator: Physics found. {base_gb}GB base + {default_ctx} ctx. Setting util to {vllm_util:.3f}")
            else:
                # SAFETY NET
                safe_ctx = cfg.get('vllm', {}).get('uncalibrated_safe_ctx', 8192)
                safe_vram = cfg.get('vllm', {}).get('uncalibrated_safe_vram_gb', 4.0)
                vllm_util = (safe_vram / total_vram)
                default_ctx = safe_ctx
                logger.warning(f"⚠️ SmartAllocator: No calibration for {model}. SAFETY NET: {safe_ctx} ctx @ {vllm_util:.3f} util.")
            
            vllm_util = min(0.95, max(0.1, vllm_util))
            # --- END SMART ALLOCATOR ---

            if not os.system(f"netstat -ano | findstr :{vllm_port} > nul"):
                logger.info(f"ℹ️ vLLM already running on port {vllm_port}.")
            else:
                logger.info(f"🚀 Starting vLLM [{model}] on port {vllm_port}...")
                hf_cache = get_hf_home()
                cmd = [
                    "docker", "run", "--gpus", "all", "-d", 
                    "--name", "vllm-server",
                    "-p", f"{vllm_port}:8000",
                    "-v", f"{hf_cache}:/root/.cache/huggingface",
                    "vllm/vllm-openai",
                    "--model", model,
                    "--gpu-memory-utilization", str(round(vllm_util, 3)),
                    "--max-model-len", str(default_ctx)
                ]
                # We use subprocess.run for docker -d as it returns immediately
                subprocess.run(cmd, capture_output=True)
                wait_for_port(vllm_port, timeout=300) # vLLM can take a while to pull/load

    # 3. STT Models
    for model in target.get('stt', []):
        port = cfg['stt_loadout'].get(model)
        if not port:
            logger.error(f"Unknown STT model in loadout: {model}")
            continue
        
        if os.system(f"netstat -ano | findstr :{port} > nul"):
            if not soft: logger.warning(f"⚠️ STT [{model}] detected despite purge! (Ghost Process?)")
            else: logger.info(f"ℹ️ STT [{model}] already running.")
        else:
            logger.info(f"🚀 Starting STT [{model}] on port {port}...")
            # Broadcast HF_HOME
            os.environ['HF_HOME'] = get_hf_home()
            cmd = [python_exe, stt_script, "--port", str(port), "--model", model]
            start_server(cmd, loud=loud)
            wait_for_port(port)

    # 4. TTS Models
    for variant in target.get('tts', []):
        port = cfg['tts_loadout'].get(variant)
        if not port:
            logger.error(f"Unknown TTS variant in loadout: {variant}")
            continue
            
        if os.system(f"netstat -ano | findstr :{port} > nul"):
            if not soft: logger.warning(f"⚠️ TTS [{variant}] detected despite purge! (Ghost Process?)")
            else: logger.info(f"ℹ️ TTS [{variant}] already running.")
        else:
            logger.info(f"🚀 Starting TTS [{variant}] on port {port}...")
            # Broadcast HF_HOME
            os.environ['HF_HOME'] = get_hf_home()
            cmd = [python_exe, tts_script, "--port", str(port), "--variant", variant]
            start_server(cmd, loud=loud)
            wait_for_port(port, timeout=120)

def kill_loadout(target):
    cfg = load_config()
    if target == "all":
        kill_all_jarvis_services()
    else:
        # Check for service name matches
        port = None
        if target == "ollama":
            port = cfg['ports']['ollama']
        elif target == "vllm":
            port = cfg['ports'].get('vllm')
        elif target == "sts":
            port = cfg['ports']['sts']
        else:
            port = cfg['stt_loadout'].get(target) or cfg['tts_loadout'].get(target)
            
        if port:
            kill_process_on_port(port)
        else:
            logger.error(f"Unknown target to kill: {target}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Loadout Manager")
    parser.add_argument("--status", action="store_true", help="Show cluster health")
    parser.add_argument("--apply", type=str, help="Apply a loadout preset (Implies Strict Purge)")
    parser.add_argument("--soft", action="store_true", help="Disable strict purge (Layer on top of existing services)")
    parser.add_argument("--kill", type=str, help="Kill a specific model or 'all'")
    parser.add_argument("--loud", action="store_true", help="Show console windows for started servers")
    
    args = parser.parse_args()
    
    if args.status:
        print_status()
    elif args.apply:
        apply_loadout(args.apply, loud=args.loud, soft=args.soft)
    elif args.kill:
        kill_loadout(args.kill)
    else:
        parser.print_help()
