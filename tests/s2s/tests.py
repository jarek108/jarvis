import requests
import os
import sys
import time
import json

# Force UTF-8 for console output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Allow importing utils and config from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, get_system_health

# ANSI Colors for live reporting
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def run_test(trim_length=80, skip_health=False, loadout_id="default"):
    cfg = load_config()
    active_env = []
    if not skip_health:
        health = get_system_health()
        active_env = [name for name, info in health.items() if info['status'] == "ON"]

    url = f"http://127.0.0.1:{cfg['ports']['s2s']}/process"
    
    # Define scenarios
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)

    scenarios = [
        {"name": "english_std", "lang": "en"},
        {"name": "polish_implicit", "lang": "", "input": "polish_std"},
        {"name": "polish_explicit", "lang": "pl", "input": "polish_std"}
    ]

    all_passed = True

    for s in scenarios:
        input_file = s.get('input', s['name'])
        audio_path = os.path.join(input_base, f"{input_file}.wav")
        output_path = os.path.join(results_dir, f"{loadout_id}_{s['name']}.wav")

        if not os.path.exists(audio_path):
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": f"Input missing: {s['name']}.wav", "env": active_env}
            all_passed = False
        else:
            try:
                start_time = time.perf_counter()
                with open(audio_path, "rb") as f:
                    files = {"file": f}
                    data = {"language_id": s.get('lang', '')}
                    response = requests.post(url, files=files, data=data)
                duration = time.perf_counter() - start_time
                
                # Project root relative path
                rel_out = os.path.relpath(output_path, os.path.join(os.path.dirname(__file__), "..", ".."))

                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    
                    display_path = rel_out
                    if len(display_path) > trim_length:
                        display_path = "..." + display_path[-(trim_length-3):]

                    # Extract metrics
                    stt_inf = response.headers.get("X-Metric-STT-Inference", "0.00")
                    llm_tot = response.headers.get("X-Metric-LLM-Total", "0.00")
                    tts_inf = response.headers.get("X-Metric-TTS-Inference", "0.00")
                    
                    # Extract text results
                    stt_text = response.headers.get("X-Result-STT", "N/A")
                    llm_text = response.headers.get("X-Result-LLM", "N/A")
                    
                    # Extract model names
                    stt_model = response.headers.get("X-Model-STT", "STT")
                    llm_model = response.headers.get("X-Model-LLM", "LLM")
                    tts_model = response.headers.get("X-Model-TTS", "TTS")
                    
                    res_obj = {
                        "name": s['name'], 
                        "status": "PASSED", 
                        "duration": duration, 
                        "result": display_path, 
                        "stt_inf": float(stt_inf),
                        "llm_tot": float(llm_tot),
                        "tts_inf": float(tts_inf),
                        "stt_text": stt_text,
                        "llm_text": llm_text,
                        "stt_model": stt_model,
                        "llm_model": llm_model,
                        "tts_model": tts_model,
                        "env": active_env
                    }
                else:
                    res_obj = {"name": s['name'], "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "env": active_env}
                    all_passed = False
            except Exception as e:
                res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": str(e), "env": active_env}
                all_passed = False

        # --- LIVE NICE MULTI-LINE ROW ---
        if res_obj['status'] == "PASSED":
            main_row = f"  - {format_status(res_obj['status'])} {res_obj['name']} (Total: {res_obj['duration']:.2f}s)\n"
            sys.stdout.write(main_row)
            sys.stdout.write(f"    \t🎙️ {res_obj['stt_inf']:.2f}s | [{res_obj['stt_model']}] | Text: \"{res_obj['stt_text']}\"\n")
            sys.stdout.write(f"    \t🧠 {res_obj['llm_tot']:.2f}s | [{res_obj['llm_model']}] | Text: \"{res_obj['llm_text']}\"\n")
            sys.stdout.write(f"    \t🔊 {res_obj['tts_inf']:.2f}s | [{res_obj['tts_model']}] | Path: {res_obj['result']}\n")
        else:
            row = f"  - {format_status(res_obj['status'])} | {res_obj['duration']:.2f}s | Scenario: {res_obj['name']:<15} | Result: {res_obj['result']}\n"
            sys.stdout.write(row)
        
        # --- MACHINE OUTPUT ---
        sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
        sys.stdout.flush()
    
    return all_passed

if __name__ == "__main__":
    run_test(loadout_id="default")