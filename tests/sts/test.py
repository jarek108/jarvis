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
    url = f"http://127.0.0.1:{cfg['ports']['sts']}{endpoint}"
    
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
                        if response.status_code != 200:
                            res_obj = {"name": s['name'], "status": "FAILED", "duration": time.perf_counter() - start_time, "result": f"HTTP {response.status_code}", "mode": "STREAM"}
                            report_scenario_result(res_obj)
                            continue

                        audio_content = b""
                        metrics = {}
                        llm_text = ""
                        stt_text = ""
                        
                        # PROTOCOL PARSER
                        # [TYPE(1b)][LEN(4b)][DATA(LENb)]
                        stream_reader = response.raw
                        while True:
                            header = stream_reader.read(5)
                            if not header or len(header) < 5:
                                break
                            
                            type_char = chr(header[0])
                            length = int.from_bytes(header[1:], 'little')
                            payload = stream_reader.read(length)
                            
                            if type_char == 'T': # Text Frame
                                frame_data = json.loads(payload.decode())
                                if frame_data['role'] == "user":
                                    stt_text = frame_data['text']
                                else:
                                    llm_text += " " + frame_data['text']
                            elif type_char == 'A': # Audio Frame
                                audio_content += payload
                            elif type_char == 'M': # Metrics Frame
                                metrics = json.loads(payload.decode())
                                break
                        
                        duration = time.perf_counter() - start_time
                        
                        if response.status_code == 200:
                            with open(output_path, "wb") as f_out:
                                f_out.write(audio_content)
                            
                            res_obj = {
                                "name": s['name'], "status": "PASSED", "duration": duration, 
                                "result": os.path.relpath(output_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                                "mode": "STREAM", "metrics": metrics,
                                "stt_model": response.headers.get("X-Model-STT"),
                                "llm_model": response.headers.get("X-Model-LLM"),
                                "tts_model": response.headers.get("X-Model-TTS"),
                                "input_file": audio_path,
                                "output_file": output_path
                            }
                        else:
                            res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "mode": "STREAM", "input_file": audio_path}
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
                                "tts_model": response.headers.get("X-Model-TTS"),
                                "input_file": audio_path,
                                "output_file": output_path
                            }
                        else:
                            res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "mode": "WAV", "input_file": audio_path}
            except Exception as e:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e), "mode": "STREAM" if stream else "WAV"}

        report_scenario_result(res_obj)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis sts Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    parser.add_argument("--purge", action="store_true", help="Kill extra Jarvis services")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()

    # sts Audit wrapper
    def test_wrapper():
        vram_start = get_gpu_vram_usage()
        # Run both modes
        run_test_suite(args.loadout, stream=False)
        run_test_suite(args.loadout, stream=True)
        
        vram_peak = get_gpu_vram_usage()
        # We don't read from loadout file anymore, we just audit if it was Ollama
        # Ideally we'd pass this info through, but for now we skip detailed audit if not easily available
        print("\n" + "-"*40)
        print(f"VRAM AUDIT: {args.loadout.upper()}")
        print(f"  Peak Total Usage: {vram_peak:.1f} GB")
        print("-"*40 + "\n")

    # Note: we need to handle the models list here if we want to run this script standalone,
    # but normally it's called via runner.py which handles lifecycle.
    # For now, we just pass dummy values to avoid crash if run directly.
    run_test_lifecycle(
        domain="sts",
        setup_name=args.loadout,
        models=[], # In standalone, we don't have the list
        purge=args.purge,
        full=args.full,
        test_func=test_wrapper,
        benchmark_mode=args.benchmark_mode
    )
