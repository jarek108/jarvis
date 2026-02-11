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

def calculate_similarity(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def run_test_suite(model_id, trim_length=80):
    cfg = load_config()
    port = cfg['stt_loadout'].get(model_id)
    if not port:
        print(f"FAILED: Model ID '{model_id}' not found in configuration.")
        return False
        
    url = f"http://127.0.0.1:{port}/transcribe"
    input_dir = os.path.join(os.path.dirname(__file__), "whisper", "input_data")
    
    meta_path = os.path.join(input_dir, "metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    lang_map = {"pl": "Polish", "fr": "French", "zh": "Chinese", "en": "English"}

    for filename, info in metadata.items():
        audio_path = os.path.join(input_dir, filename)
        if not os.path.exists(audio_path): continue

        ground_truth = info['text']
        target_lang = info['lang']
        lang_name = lang_map.get(target_lang, target_lang.upper())

        test_modes = [
            {"mode": "implicit", "hint": None},
            {"mode": "explicit", "hint": target_lang},
            {"mode": "misleading", "hint": "en"} if target_lang != "en" else None
        ]

        for mode in test_modes:
            if not mode: continue
            scenario_name = f"{lang_name}, {mode['mode']}"
            
            try:
                start_time = time.perf_counter()
                with open(audio_path, "rb") as f:
                    files = {"file": f}
                    data = {"language": mode['hint']} if mode['hint'] else {}
                    response = requests.post(url, files=files, data=data)
                duration = time.perf_counter() - start_time
                
                if response.status_code == 200:
                    result = response.json()
                    transcription = result.get('text', '').replace("\n", " ").strip()
                    similarity = calculate_similarity(transcription, ground_truth)
                    
                    ascii_text = transcription.encode('ascii', 'replace').decode('ascii')
                    if len(ascii_text) > trim_length:
                        ascii_text = ascii_text[:trim_length] + "..."

                    res_obj = {
                        "name": scenario_name,
                        "status": "PASSED",
                        "duration": duration,
                        "result": f"Match: {similarity:.1%} | [{ascii_text}]"
                    }
                else:
                    res_obj = { "name": scenario_name, "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}" }
            except Exception as e:
                res_obj = { "name": scenario_name, "status": "FAILED", "duration": 0, "result": str(e) }
            
            report_scenario_result(res_obj)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis STT Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    parser.add_argument("--purge", action="store_true", help="Kill extra Jarvis services")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()

    # Load loadout to get model_id
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    loadout_path = os.path.join(project_root, "tests", "loadouts", f"{args.loadout}.yaml")
    
    if not os.path.exists(loadout_path):
        print(f"❌ ERROR: Loadout '{args.loadout}' not found.")
        sys.exit(1)
        
    with open(loadout_path, "r") as f:
        l_data = yaml.safe_load(f)
        stt_list = l_data.get('stt', [])
        if not stt_list:
            print(f"❌ ERROR: Loadout '{args.loadout}' defines no STT component.")
            sys.exit(1)
        target_model = stt_list[0]

    run_test_lifecycle(
        domain="stt",
        loadout_name=args.loadout,
        purge=args.purge,
        full=args.full,
        test_func=lambda: run_test_suite(target_model),
        benchmark_mode=args.benchmark_mode
    )
