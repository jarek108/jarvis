import requests
import os
import sys
import time
import json
import argparse
import yaml
from typing import Optional

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, report_scenario_result, ensure_utf8_output, run_test_lifecycle, get_gpu_vram_usage, check_ollama_offload

# Ensure UTF-8 output
ensure_utf8_output()

def run_test_suite(loadout_id, stream=False, trim_length=80):
    cfg = load_config()
    endpoint = "/process_stream" if stream else "/process"
    url = f"http://127.0.0.1:{cfg['ports']['s2s']}{endpoint}"
    
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)

    scenarios = [
        {"name": "english_std", "lang": "en"},
        {"name": "polish_explicit", "lang": "pl", "input": "polish_std"},
        {"name": "short2long", "lang": "en", "input": "short_dog_story"},
        {"name": "long2short", "lang": "en", "input": "long_book_quote"}
    ]

    for s in scenarios:
        input_file = s.get('input', s['name'])
        audio_path = os.path.join(input_base, f"{input_file}.wav")
        suffix = "_stream" if stream else ""
        output_path = os.path.join(results_dir, f"{loadout_id}_{s['name']}{suffix}.wav")

        if not os.path.exists(audio_path):
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": f"Input missing: {input_file}.wav", "mode": "STREAM" if stream else "WAV"}
        else:
            try:
                start_time = time.perf_counter()
                with open(audio_path, "rb") as f:
                    files = {"file": f}
                    data = {"language_id": s.get('lang', '')}
                    
                    if stream:
                        response = requests.post(url, files=files, data=data, stream=True)
                        raw_content = b""
                        for chunk in response.iter_content(chunk_size=4096):
                            raw_content += chunk
                        
                        duration = time.perf_counter() - start_time
                        
                        metrics = {}
                        audio_content = raw_content
                        if b"\nMETRICS_JSON:" in raw_content:
                            parts = raw_content.split(b"\nMETRICS_JSON:")
                            audio_content = parts[0]
                            try: metrics = json.loads(parts[1].decode())
                            except: pass

                        if response.status_code == 200:
                            with open(output_path, "wb") as f_out:
                                f_out.write(audio_content)
                            
                            res_obj = {
                                "name": s['name'], "status": "PASSED", "duration": duration, 
                                "result": os.path.relpath(output_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                                "mode": "STREAM", "metrics": metrics,
                                "stt_model": response.headers.get("X-Model-STT"),
                                "llm_model": response.headers.get("X-Model-LLM"),
                                "tts_model": response.headers.get("X-Model-TTS")
                            }
                        else:
                            res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "mode": "STREAM"}
                    else:
                        response = requests.post(url, files=files, data=data)
                        duration = time.perf_counter() - start_time
                        if response.status_code == 200:
                            with open(output_path, "wb") as f_out:
                                f_out.write(response.content)
                            
                            res_obj = {
                                "name": s['name'], "status": "PASSED", "duration": duration,
                                "result": os.path.relpath(output_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                                "mode": "WAV",
                                "stt_inf": float(response.headers.get("X-Metric-STT-Inference", 0)),
                                "llm_tot": float(response.headers.get("X-Metric-LLM-Total", 0)),
                                "tts_inf": float(response.headers.get("X-Metric-TTS-Inference", 0)),
                                "stt_text": response.headers.get("X-Result-STT"),
                                "llm_text": response.headers.get("X-Result-LLM"),
                                "stt_model": response.headers.get("X-Model-STT"),
                                "llm_model": response.headers.get("X-Model-LLM"),
                                "tts_model": response.headers.get("X-Model-TTS")
                            }
                        else:
                            res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "mode": "WAV"}
            except Exception as e:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e), "mode": "STREAM" if stream else "WAV"}

        report_scenario_result(res_obj)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis S2S Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    parser.add_argument("--purge", action="store_true", help="Kill extra Jarvis services")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()

    # S2S Audit wrapper
    def test_wrapper():
        vram_start = get_gpu_vram_usage()
        # Run both modes
        run_test_suite(args.loadout, stream=False)
        run_test_suite(args.loadout, stream=True)
        
        vram_peak = get_gpu_vram_usage()
        # Get active LLM from loadout for audit
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        loadout_path = os.path.join(project_root, "tests", "loadouts", f"{args.loadout}.yaml")
        with open(loadout_path, "r") as f:
            l_data = yaml.safe_load(f)
            active_llm = l_data.get('llm', 'gpt-oss:20b')
            
        is_ok, vram_used, total_size = check_ollama_offload(active_llm)
        print("\n" + "-"*40)
        print(f"VRAM AUDIT: {args.loadout.upper()}")
        print(f"  Peak Total Usage: {vram_peak:.1f} GB")
        if total_size > 0:
            status_txt = "FULL VRAM" if is_ok else "🚨 RAM SWAP"
            print(f"  Model Placement: {status_txt} ({vram_used:.1f}GB / {total_size:.1f}GB in VRAM)")
        print("-"*40 + "\n")

    run_test_lifecycle(
        domain="s2s",
        loadout_name=args.loadout,
        purge=args.purge,
        full=args.full,
        test_func=test_wrapper,
        benchmark_mode=args.benchmark_mode
    )
