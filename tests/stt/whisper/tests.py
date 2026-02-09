import requests
import os
import sys
import time
import json
import difflib

# Allow importing utils and config from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import load_config, get_active_env_list, report_scenario_result, ensure_utf8_output, calculate_similarity

# Ensure UTF-8 output
ensure_utf8_output()

def run_test(model_id="faster-whisper-base", trim_length=80):
    cfg = load_config()
    active_env = get_active_env_list()

    port = cfg['stt_loadout'].get(model_id)
    if not port:
        print(f"FAILED: Model ID '{model_id}' not found in loadout.")
        return False
        
    url = f"http://127.0.0.1:{port}/transcribe"
    input_dir = os.path.join(os.path.dirname(__file__), "input_data")
    
    meta_path = os.path.join(input_dir, "metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Naming convention: Sample, Mode
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
                        "result": f"Match: {similarity:.1%} | [{ascii_text}]",
                        "env": active_env
                    }
                else:
                    res_obj = { "name": scenario_name, "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "env": active_env }
            except Exception as e:
                res_obj = { "name": scenario_name, "status": "FAILED", "duration": 0, "result": str(e), "env": active_env }
            
            # Use unified reporting
            report_scenario_result(res_obj)

if __name__ == "__main__":
    run_test(model_id="faster-whisper-base")