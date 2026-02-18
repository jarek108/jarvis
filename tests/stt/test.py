import requests
import os
import sys
import time
import json
import argparse
import yaml

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
import test_utils
from test_utils.collectors import BaseReporter, StdoutReporter

# Ensure UTF-8 output
utils.ensure_utf8_output()

def calculate_similarity(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def run_test_suite(model_id, scenarios_to_run=None, trim_length=80, output_dir=None, reporter: BaseReporter = None):
    cfg = utils.load_config()
    if not reporter:
        reporter = StdoutReporter()

    port = cfg['stt_loadout'].get(model_id)
    if not port:
        print(f"FAILED: Model ID '{model_id}' not found in configuration.")
        return False
        
    url = f"http://127.0.0.1:{port}/transcribe"
    input_dir = os.path.join(os.path.dirname(__file__), "whisper", "input_data")
    
    # Use session output dir if provided
    final_results_dir = output_dir if output_dir else os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(final_results_dir, exist_ok=True)
    
    for s in scenarios_to_run:
        audio_path = os.path.join(input_dir, s['input'])
        ground_truth = s.get('expected', '')
        
        # Initialize result object with metadata immediately
        res_obj = {
            "name": s['name'],
            "stt_model": model_id,
            "input_file": audio_path,
            "input_text": ground_truth,
            "mode": "WAV"
        }

        if not os.path.exists(audio_path):
            res_obj.update({"status": "FAILED", "duration": 0, "result": f"Input file missing: {s['input']}"})
            report_scenario_result(res_obj)
            continue
        
        try:
            start_time = time.perf_counter()
            with open(audio_path, "rb") as f:
                files = {"file": f}
                data = {"language": s.get('hint')} if s.get('hint') else {}
                response = requests.post(url, files=files, data=data)
            duration = time.perf_counter() - start_time
            
            if response.status_code == 200:
                result = response.json()
                transcription = result.get('text', '').replace("\n", " ").strip()
                similarity = calculate_similarity(transcription, ground_truth)
                
                display_text = transcription
                if len(display_text) > trim_length:
                    display_text = display_text[:trim_length] + "..."

                res_obj.update({
                    "status": "PASSED",
                    "duration": duration,
                    "result": f"Match: {similarity:.1%} | [{display_text}]",
                    "match_pct": similarity,
                    "output_text": transcription,
                    "vram_peak": utils.get_gpu_vram_usage()
                })
            else:
                res_obj.update({ "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}" })
        except Exception as e:
            res_obj.update({ "status": "FAILED", "duration": 0, "result": str(e) })
        
        reporter.report(res_obj)

if __name__ == "__main__":
    # Note: Standalone mode updated to load default scenarios
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "scenarios.yaml"), "r", encoding="utf-8") as f:
        all_scenarios = yaml.safe_load(f)
    
    # Simple list conversion for standalone
    scenarios = [{"name": k, **v} for k, v in all_scenarios.items()]
    
    # For now, keep argparse for manual triggers
    parser = argparse.ArgumentParser(description="Jarvis STT Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    args = parser.parse_args()

    # Load model from loadout
    cfg = load_config()
    l_path = os.path.join(os.path.dirname(script_dir), "loadouts", f"{args.loadout}.yaml")
    with open(l_path, "r", encoding="utf-8") as f:
        target_model = yaml.safe_load(f).get('stt')[0]

    test_utils.run_test_lifecycle(
        domain="stt", setup_name=args.loadout, models=[target_model],
        purge_on_entry=True, purge_on_exit=True, full=False,
        test_func=lambda: run_test_suite(target_model, scenarios_to_run=scenarios)
    )
