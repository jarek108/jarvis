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
python manage_loadout.py --apply vanilla_fast
python manage_loadout.py --apply eng_turbo
python manage_loadout.py --apply multilingual_accurate

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
from utils import get_system_health, load_config, kill_process_on_port, wait_for_port, start_server

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
    
    for name, info in health.items():
        status = info['status']
        color = GRAY
        if status == "ON": color = GREEN
        elif status == "UNHEALTHY": color = RED
        elif status == "BUSY": color = YELLOW
        
        details = ""
        if name == "Ollama":
            if status == "ON":
                resident = info.get('resident_models', [])
                downloaded = info.get('downloaded_models', [])
                
                if resident:
                    details = f"{BOLD}Resident (VRAM):{RESET} {', '.join(resident)}"
                else:
                    details = "Ready (VRAM Empty)"
                
                if downloaded:
                    details += f" | {GRAY}Downloaded: {len(downloaded)}{RESET}"
                
                if not info['model_installed']:
                    details += f" | {RED}Active Model Missing{RESET}"
            else:
                details = "Ollama Service Offline"
            
        print(f"{name:<30} | {info['port']:<8} | {color}{status:<15}{RESET} | {details}")
    
    print("="*LINE_LEN + "\n")

def apply_loadout(name, loud=False):
    cfg = load_config()
    loadout_path = os.path.join(os.getcwd(), "tests", "loadouts", f"{name}.yaml")
    if not os.path.exists(loadout_path):
        loadout_path = os.path.join(os.getcwd(), "tests", "loadouts", f"{name}")
        if not os.path.exists(loadout_path):
            logger.error(f"Loadout '{name}' not found.")
            return

    with open(loadout_path, "r") as f:
        target = yaml.safe_load(f)

    logger.info(f"Applying Loadout: {target.get('description', name)}")
    
    python_exe = os.path.join(os.getcwd(), "jarvis-venv", "Scripts", "python.exe")
    stt_script = os.path.join(os.getcwd(), "servers", "stt_server.py")
    tts_script = os.path.join(os.getcwd(), "servers", "tts_server.py")

    # 1. Start Ollama if needed
    llm_port = cfg['ports']['llm']
    if not os.system(f"netstat -ano | findstr :{llm_port} > nul"):
        logger.info("ℹ️ Ollama already running.")
    else:
        logger.info("🚀 Starting Ollama...")
        start_server(["ollama", "serve"], loud=loud)
        wait_for_port(llm_port)

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
        ports = [cfg['ports']['llm'], cfg['ports']['s2s']] + list(cfg['stt_loadout'].values()) + list(cfg['tts_loadout'].values())
        for p in ports:
            kill_process_on_port(p)
    else:
        p = cfg['stt_loadout'].get(target) or cfg['tts_loadout'].get(target)
        if p:
            kill_process_on_port(p)
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
