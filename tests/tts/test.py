import requests
import os
import sys
import time
import json
import argparse
import yaml

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, report_scenario_result, ensure_utf8_output, run_test_lifecycle

# Ensure UTF-8 output
ensure_utf8_output()

def run_test_suite(variant_id, trim_length=80):
    cfg = load_config()
    port = cfg['tts_loadout'].get(variant_id)
    if not port:
        print(f"FAILED: Variant ID '{variant_id}' not found in configuration.")
        return False
        
    url = f"http://127.0.0.1:{port}/tts"
    results_dir = os.path.join(os.path.dirname(__file__), "chatterbox", "results")
    os.makedirs(results_dir, exist_ok=True)
    
    scenarios = [
        {"name": "standard", "text": "Hello, I am Jarvis. How can I assist you today?", "lang": "en"},
        {"name": "polish", "text": "Cześć, nazywam się Jarvis. Jak mogę Ci dzisiaj pomóc?", "lang": "pl"},
        {"name": "french", "text": "Bonjour, je m'appelle Jarvis. Comment puis-je vous aider?", "lang": "fr"},
        {"name": "chinese", "text": "你好，我叫贾维斯。我今天能为您做什么？", "lang": "zh"},
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
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rel_path = os.path.relpath(out_path, project_root)

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
                    "tts_model": variant_id,
                    "output_file": out_path,
                    "input_text": s['text']
                }
            else:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "input_text": s['text']}
        except Exception as e:
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e)}

        report_scenario_result(res_obj)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis TTS Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    parser.add_argument("--purge", action="store_true", help="Kill extra Jarvis services")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()

    # Load loadout to get variant_id
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    loadout_path = os.path.join(project_root, "tests", "loadouts", f"{args.loadout}.yaml")
    
    if not os.path.exists(loadout_path):
        print(f"❌ ERROR: Loadout '{args.loadout}' not found.")
        sys.exit(1)
        
    with open(loadout_path, "r") as f:
        l_data = yaml.safe_load(f)
        tts_val = l_data.get('tts', [])
        if not tts_val:
            print(f"❌ ERROR: Loadout '{args.loadout}' defines no TTS component.")
            sys.exit(1)
        target_variant = tts_val[0] if isinstance(tts_val, list) else tts_val

    # Standalone support
    run_test_lifecycle(
        domain="tts",
        setup_name=args.loadout,
        models=[target_variant],
        purge=args.purge,
        full=args.full,
        test_func=lambda: run_test_suite(target_variant),
        benchmark_mode=args.benchmark_mode
    )
