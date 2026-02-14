import requests
import os
import sys
import time
import json
import argparse
import yaml

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, report_scenario_result, ensure_utf8_output, run_test_lifecycle, get_gpu_vram_usage

# Ensure UTF-8 output
ensure_utf8_output()

def run_test_suite(variant_id, scenarios_to_run=None, trim_length=80):
    cfg = load_config()
    port = cfg['tts_loadout'].get(variant_id)
    if not port:
        print(f"FAILED: Variant ID '{variant_id}' not found in configuration.")
        return False
        
    url = f"http://127.0.0.1:{port}/tts"
    results_dir = os.path.join(os.path.dirname(__file__), "chatterbox", "results")
    os.makedirs(results_dir, exist_ok=True)
    
    for s in scenarios_to_run:
        payload = {"text": s['text'], "voice": "default", "language_id": s.get('lang', 'en')}
        out_path = os.path.join(results_dir, f"{variant_id}_{s['name']}.wav")
        # Relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
                    "input_text": s['text'],
                    "vram_peak": get_gpu_vram_usage()
                }
            else:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "input_text": s['text']}
        except Exception as e:
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e)}

        report_scenario_result(res_obj)

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "scenarios.yaml"), "r") as f:
        all_scenarios = yaml.safe_load(f)
    scenarios = [{"name": k, **v} for k, v in all_scenarios.items()]

    parser = argparse.ArgumentParser(description="Jarvis TTS Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    args = parser.parse_args()

    cfg = load_config()
    l_path = os.path.join(os.path.dirname(script_dir), "loadouts", f"{args.loadout}.yaml")
    with open(l_path, "r") as f:
        target_variant = yaml.safe_load(f).get('tts')[0]

    run_test_lifecycle(
        domain="tts", setup_name=args.loadout, models=[target_variant],
        purge_on_entry=True, purge_on_exit=True, full=False,
        test_func=lambda: run_test_suite(target_variant, scenarios_to_run=scenarios)
    )
