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
import utils
import test_utils

# Ensure UTF-8 output
utils.ensure_utf8_output()

def run_test_suite(loadout_id, scenarios_to_run=None, stream=False, trim_length=80, output_dir=None, reporter=None):
    cfg = utils.load_config()
    if not reporter:
        from test_utils.collectors import StdoutReporter
        reporter = StdoutReporter()

    endpoint = "/process_stream" if stream else "/process"
    url = f"http://127.0.0.1:{cfg['ports']['sts']}{endpoint}"
    
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    # Use session output dir if provided
    final_results_dir = output_dir if output_dir else os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(final_results_dir, exist_ok=True)

    for s in scenarios_to_run:
        audio_path = os.path.join(input_base, s['input'])
        suffix = "_stream" if stream else ""
        
        # Sanitize model name for filesystem (Windows doesn't allow '/' or ':')
        safe_id = loadout_id.replace("/", "--").replace(":", "-")
        output_path = os.path.join(final_results_dir, f"{safe_id}_{s['name']}{suffix}.wav")

        # Initialize result object with metadata immediately
        # loadout_id usually looks like "stt_llm_tts"
        parts = loadout_id.split("_")
        res_obj = {
            "name": s['name'],
            "mode": "STREAM" if stream else "WAV",
            "stt_model": parts[0] if len(parts) > 0 else "N/A",
            "llm_model": parts[1] if len(parts) > 1 else "N/A",
            "tts_model": parts[2] if len(parts) > 2 else "N/A",
            "input_file": audio_path,
            "output_file": output_path,
            "streaming": stream,
            "vram_prior": 0.0 # Placeholder
        }

        if not os.path.exists(audio_path):
            res_obj.update({"status": "FAILED", "duration": 0, "result": f"Input missing: {s['input']}"})
        else:
            try:
                start_time = time.perf_counter()
                with open(audio_path, "rb") as f:
                    files = {"file": f}
                    data = {"language_id": s.get('lang', '')}
                    
                    if stream:
                        response = requests.post(url, files=files, data=data, stream=True)
                        if response.status_code != 200:
                            res_obj.update({"status": "FAILED", "duration": time.perf_counter() - start_time, "result": f"HTTP {response.status_code}"})
                        else:
                            audio_content = b""; metrics = {}; llm_text = ""; stt_text = ""
                            chunks = []; stream_reader = response.raw
                            while True:
                                header = stream_reader.read(5)
                                if not header or len(header) < 5: break
                                type_char = chr(header[0]); length = int.from_bytes(header[1:], 'little')
                                payload = stream_reader.read(length)
                                if type_char == 'T': 
                                    frame_data = json.loads(payload.decode())
                                    if frame_data['role'] == "user": stt_text = frame_data['text']
                                    else: 
                                        llm_text += " " + frame_data['text']
                                        chunks.append({"text": frame_data['text'], "end": time.perf_counter() - start_time})
                                elif type_char == 'A': audio_content += payload
                                elif type_char == 'M': metrics = json.loads(payload.decode()); break
                            
                            duration = time.perf_counter() - start_time
                            with open(output_path, "wb") as f_out: f_out.write(audio_content)
                            res_obj.update({"status": "PASSED", "duration": duration, "result": os.path.relpath(output_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "metrics": metrics, "vram_peak": utils.get_gpu_vram_usage(), "stt_text": stt_text, "llm_text": llm_text, "chunks": chunks})
                    else:
                            
                        response = requests.post(url, files=files, data=data)
                        duration = time.perf_counter() - start_time
                        if response.status_code == 200:
                            with open(output_path, "wb") as f_out: f_out.write(response.content)
                            res_obj.update({
                                "status": "PASSED", "duration": duration, "result": os.path.relpath(output_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 
                                "stt_inf": float(response.headers.get("X-Metric-STT-Inference", 0)), 
                                "llm_tot": float(response.headers.get("X-Metric-LLM-Total", 0)), 
                                "tts_inf": float(response.headers.get("X-Metric-TTS-Inference", 0)), 
                                "stt_text": response.headers.get("X-Result-STT"), 
                                "llm_text": response.headers.get("X-Result-LLM"), 
                                "vram_peak": utils.get_gpu_vram_usage()
                            })
                        else:
                            res_obj.update({"status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}"})
            except Exception as e:
                res_obj.update({"status": "FAILED", "duration": 0, "result": str(e)})

        reporter.report(res_obj)

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "scenarios.yaml"), "r") as f:
        all_scenarios = yaml.safe_load(f)
    scenarios = [{"name": k, **v} for k, v in all_scenarios.items()]

    parser = argparse.ArgumentParser()
    parser.add_argument("--loadout", type=str, required=True)
    args = parser.parse_args()

    test_utils.run_test_lifecycle(
        domain="sts", setup_name=args.loadout, models=[], purge_on_entry=True, purge_on_exit=True, full=False,
        test_func=lambda reporter=None: (
            run_test_suite(args.loadout, scenarios_to_run=scenarios, stream=False, reporter=reporter), 
            run_test_suite(args.loadout, scenarios_to_run=scenarios, stream=True, reporter=reporter)
        )
    )
