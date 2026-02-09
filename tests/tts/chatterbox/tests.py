import requests
import os
import sys
import time
import json

# Allow importing utils and config from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import load_config, get_active_env_list, report_scenario_result, ensure_utf8_output

# Ensure UTF-8 output
ensure_utf8_output()

def run_test(variant_id="chatterbox-eng", trim_length=80, skip_health=False):
    cfg = load_config()
    active_env = get_active_env_list()

    port = cfg['tts_loadout'].get(variant_id)
    if not port:
        print(f"FAILED: Variant ID '{variant_id}' not found in loadout.")
        return False
        
    url = f"http://127.0.0.1:{port}/tts"
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # MERGED SCENARIOS
    scenarios = [
        # Multilingual
        {"name": "standard", "text": "Hello, I am Jarvis. How can I assist you today?", "lang": "en"},
        {"name": "polish", "text": "Cześć, nazywam się Jarvis. Jak mogę Ci dzisiaj pomóc?", "lang": "pl"},
        {"name": "french", "text": "Bonjour, je m'appelle Jarvis. Comment puis-je vous aider?", "lang": "fr"},
        {"name": "chinese", "text": "你好，我叫贾维斯。我今天能为您做什么？", "lang": "zh"},
        # Emotional / Paralinguistic
        {"name": "implicit_excited", "text": "Oh my god! This Blackwell architecture is incredible! Everything is so fast!!!", "lang": "en"},
        {"name": "implicit_serious", "text": "The system will undergo maintenance in ten minutes. Please save your work.", "lang": "en"},
        {"name": "implicit_hesitant", "text": "I... I'm not quite sure if that's the right direction, but... we can try.", "lang": "en"},
        {"name": "explicit_laugh", "text": "[laugh] That is actually very funny! I didn't see that coming.", "lang": "en"},
        {"name": "explicit_cough", "text": "[cough] Excuse me, the server room is a bit dusty today.", "lang": "en"},
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

                res_obj = {
                    "name": s['name'], 
                    "status": "PASSED", 
                    "duration": duration, 
                    "result": display_path, 
                    "env": active_env
                }
            else:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "env": active_env}
        except Exception as e:
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e), "env": active_env}

        # Use unified reporting
        report_scenario_result(res_obj)

if __name__ == "__main__":
    run_test(variant_id="chatterbox-eng")