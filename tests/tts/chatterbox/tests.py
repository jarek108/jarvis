import requests
import os
import sys
import time
import json

import json

# Force UTF-8 for console output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Allow importing utils and config from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import load_config, get_system_health

# ANSI Colors for live reporting
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def run_test(variant_id="chatterbox-eng", trim_length=80, skip_health=False):
    cfg = load_config()
    active_env = []
    if not skip_health:
        health = get_system_health()
        active_env = [name for name, info in health.items() if info['status'] == "ON"]

    port = cfg['tts_loadout'].get(variant_id)
    if not port:
        print(f"FAILED: Variant ID '{variant_id}' not found in loadout.")
        return False
        
    url = f"http://127.0.0.1:{port}/tts"
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # ... (scenarios defined here)
    scenarios = [
        # English / General
        {"name": "standard", "text": "Hello, I am Jarvis. How can I assist you today?", "lang": "en"},
        {"name": "excited_eng", "text": "Wow! That is absolutely incredible! I can't believe we did it!!!", "lang": "en"},
        {"name": "serious", "text": "The system will undergo maintenance in ten minutes. Please save your work.", "lang": "en"},
        {"name": "hesitant_eng", "text": "I... I'm not quite sure if that's the right direction, but... we can try.", "lang": "en"},
        # Multilingual
        {"name": "polish", "text": "Cześć, nazywam się Jarvis. Jak mogę Ci dzisiaj pomóc?", "lang": "pl"},
        {"name": "french", "text": "Bonjour, je m'appelle Jarvis. Comment puis-je vous aider?", "lang": "fr"},
        {"name": "chinese", "text": "你好，我叫贾维斯。我今天能为您做什么？", "lang": "zh"},
        # Turbo / Paralinguistic
        {"name": "speed_base", "text": "System ready. All parameters within normal limits.", "lang": "en"},
        {"name": "excited_turbo", "text": "Oh my god! This Blackwell architecture is incredible! Everything is so fast!!!", "lang": "en"},
        {"name": "laugh", "text": "[laugh] That is actually very funny! I didn't see that coming.", "lang": "en"},
        {"name": "cough", "text": "[cough] Excuse me, the server room is a bit dusty today.", "lang": "en"},
        {"name": "long_form", "text": "Artificial intelligence is the simulation of human intelligence processes by machines, especially computer systems.", "lang": "en"}
    ]

    for s in scenarios:
        payload = {"text": s['text'], "voice": "default", "language_id": s.get('lang', 'en')}
        out_path = os.path.join(results_dir, f"{variant_id}_{s['name']}.wav")
        # Relative to project root
        rel_path = os.path.relpath(out_path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

        try:
            start_time = time.perf_counter()
            response = requests.post(url, json=payload)
            duration = time.perf_counter() - start_time
            
            if response.status_code == 200:
                with open(out_path, "wb") as f:
                    f.write(response.content)
                
                display_path = rel_path
                if len(display_path) > trim_length:
                    display_path = "..." + display_path[-(trim_length-3):]

                # Extract metrics
                inf_time = float(response.headers.get("X-Inference-Time", 0))
                res_obj = {
                    "name": s['name'], 
                    "status": "PASSED", 
                    "duration": duration, 
                    "inference": inf_time,
                    "result": display_path, 
                    "env": active_env
                }
            else:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "inference": 0, "result": f"HTTP {response.status_code}", "env": active_env}
        except Exception as e:
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "inference": 0, "result": str(e), "env": active_env}

        # --- LIVE NICE ROW ---
        inf_str = f"{res_obj['inference']:.2f}s" if res_obj['status'] == "PASSED" else "N/A"
        row = f"  - {format_status(res_obj['status'])} | Total:{res_obj['duration']:.2f}s | Inf:{inf_str} | Scenario: {res_obj['name']:<15} | Result: {res_obj['result']}\n"
        sys.stdout.write(row)
        
        # --- MACHINE OUTPUT ---
        sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
        sys.stdout.flush()

if __name__ == "__main__":
    run_test(variant_id="chatterbox-eng")
