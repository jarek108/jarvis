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

[Subsection] : Apply a Preset Loadout
Starts only missing services defined in the preset.
python manage_loadout.py --apply base-qwen30-multi
python manage_loadout.py --apply tiny-gpt20-turbo

[Subsection] : Kill a Specific Service
python manage_loadout.py --kill faster-whisper-tiny
python manage_loadout.py --kill chatterbox-turbo

[Subsection] : Global Infrastructure Shutdown
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

# Ensure we can import from tests/
sys.path.append(os.path.join(os.getcwd(), "tests"))
from utils import get_system_health, load_config, kill_process_on_port, wait_for_port, start_server, is_vllm_docker_running, stop_vllm_docker

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"

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

def apply_loadout(name, loud=False):
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
    
    from utils import resolve_path
    python_exe = resolve_path(cfg['paths']['venv_python'])
    stt_script = os.path.join(os.getcwd(), "servers", "stt_server.py")
    tts_script = os.path.join(os.getcwd(), "servers", "tts_server.py")

    # 1. Start LLM Engine if needed
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
                start_server(["ollama", "serve"], loud=loud)
                wait_for_port(llm_port)
        elif engine == "vllm":
            vllm_port = cfg['ports'].get('vllm', 8300)
            
            # Dynamic VRAM Calculation (GB -> %)
            from utils import get_gpu_total_vram
            total_vram = get_gpu_total_vram()
            vram_map = cfg.get('vllm', {}).get('model_vram_map', {})
            
            match_gb = None
            for key, val in vram_map.items():
                if key.lower() in model.lower():
                    match_gb = val
                    break
            
            if match_gb:
                vllm_util = min(0.95, max(0.1, match_gb / total_vram))
                logger.info(f"🧠 VRAM Mapper: {model} needs {match_gb}GB. Setting util to {vllm_util:.3f}")
            else:
                vllm_util = cfg.get('vllm', {}).get('gpu_memory_utilization', 0.5)

            if not os.system(f"netstat -ano | findstr :{vllm_port} > nul"):
                logger.info(f"ℹ️ vLLM already running on port {vllm_port}.")
            else:
                logger.info(f"🚀 Starting vLLM [{model}] on port {vllm_port}...")
                hf_cache = resolve_path(cfg['paths']['huggingface_cache'])
                cmd = [
                    "docker", "run", "--gpus", "all", "-d", 
                    "--name", "vllm-server",
                    "-p", f"{vllm_port}:8000",
                    "-v", f"{hf_cache}:/root/.cache/huggingface",
                    "vllm/vllm-openai",
                    "--model", model,
                    "--gpu-memory-utilization", str(vllm_util)
                ]
                # We use subprocess.run for docker -d as it returns immediately
                subprocess.run(cmd, capture_output=True)
                wait_for_port(vllm_port, timeout=300) # vLLM can take a while to pull/load

    # 2. STT Models
    for model in target.get('stt', []):
        port = cfg['stt_loadout'].get(model)
        if not port:
            logger.error(f"Unknown STT model in loadout: {model}")
            continue
        
        if os.system(f"netstat -ano | findstr :{port} > nul"):
            logger.info(f"🚀 Starting STT [{model}] on port {port}...")
            cmd = [python_exe, stt_script, "--port", str(port), "--model", model]
            start_server(cmd, loud=loud)
            wait_for_port(port)
        else:
            logger.info(f"ℹ️ STT [{model}] already running.")

    # 3. TTS Models
    for variant in target.get('tts', []):
        port = cfg['tts_loadout'].get(variant)
        if not port:
            logger.error(f"Unknown TTS variant in loadout: {variant}")
            continue
            
        if os.system(f"netstat -ano | findstr :{port} > nul"):
            logger.info(f"🚀 Starting TTS [{variant}] on port {port}...")
            cmd = [python_exe, tts_script, "--port", str(port), "--variant", variant]
            start_server(cmd, loud=loud)
            wait_for_port(port, timeout=120)
        else:
            logger.info(f"ℹ️ TTS [{variant}] already running.")

def kill_loadout(target):
    cfg = load_config()
    if target == "all":
        from utils import kill_all_jarvis_services
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
    parser.add_argument("--apply", type=str, help="Apply a loadout preset")
    parser.add_argument("--kill", type=str, help="Kill a specific model or 'all'")
    parser.add_argument("--loud", action="store_true", help="Show console windows for started servers")
    
    args = parser.parse_args()
    
    if args.status:
        print_status()
    elif args.apply:
        apply_loadout(args.apply, loud=args.loud)
    elif args.kill:
        kill_loadout(args.kill)
    else:
        parser.print_help()
