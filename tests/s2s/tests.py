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

def run_test(trim_length=80, skip_health=False, loadout_id="default", stream=False):
    cfg = load_config()
    active_env = []
    if not skip_health:
        health = get_system_health()
        active_env = [name for name, info in health.items() if info['status'] == "ON"]

    endpoint = "/process_stream" if stream else "/process"
    url = f"http://127.0.0.1:{cfg['ports']['s2s']}{endpoint}"
    
    # Define scenarios
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)

    scenarios = [
        {"name": "english_std", "lang": "en"},
        {"name": "polish_explicit", "lang": "pl", "input": "polish_std"}
    ]

    all_passed = True

    for s in scenarios:
        input_file = s.get('input', s['name'])
        audio_path = os.path.join(input_base, f"{input_file}.wav")
        suffix = "_stream" if stream else ""
        output_path = os.path.join(results_dir, f"{loadout_id}_{s['name']}{suffix}.wav")

        if not os.path.exists(audio_path):
            res_obj = {"name": s['name'], "status": "FAILED", "duration": 0, "result": f"Input missing: {input_file}.wav", "env": active_env}
            all_passed = False
        else:
            try:
                start_time = time.perf_counter()
                files = {"file": open(audio_path, "rb")}
                data = {"language_id": s.get('lang', '')}
                
                if stream:
                    response = requests.post(url, files=files, data=data, stream=True)
                    raw_content = b""
                    for chunk in response.iter_content(chunk_size=4096):
                        raw_content += chunk
                    
                    duration = time.perf_counter() - start_time
                    
                    # Split metrics from audio
                    metrics = {}
                    audio_content = raw_content
                    if b"\nMETRICS_JSON:" in raw_content:
                        parts = raw_content.split(b"\nMETRICS_JSON:")
                        audio_content = parts[0]
                        try:
                            metrics = json.loads(parts[1].decode())
                        except:
                            pass

                    if response.status_code == 200:
                        with open(output_path, "wb") as f:
                            f.write(audio_content)
                        
                        stt_model = response.headers.get("X-Model-STT", "STT")
                        llm_model = response.headers.get("X-Model-LLM", "LLM")
                        tts_model = response.headers.get("X-Model-TTS", "TTS")

                        res_obj = {
                            "name": s['name'] + suffix, 
                            "status": "PASSED", 
                            "duration": duration, 
                            "result": os.path.relpath(output_path, os.path.join(os.path.dirname(__file__), "..", "..")), 
                            "env": active_env,
                            "stream": True,
                            "metrics": metrics,
                            "stt_model": stt_model,
                            "llm_model": llm_model,
                            "tts_model": tts_model
                        }
                    else:
                        res_obj = {"name": s['name'] + suffix, "status": "FAILED", "duration": duration, "result": f"HTTP {response.status_code}", "env": active_env}
                else:
                    response = requests.post(url, files=files, data=data)
                    duration = time.perf_counter() - start_time
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
                        stt_text = response.headers.get("X-Result-STT", "N/A")
                        llm_text = response.headers.get("X-Result-LLM", "N/A")
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
            if res_obj.get('stream'):
                m = res_obj.get('metrics', {})
                t1 = m.get('tts', [0,0])[0]
                t2 = m.get('tts', [0,0])[1]
                main_row = f"  - {format_status(res_obj['status'])} {res_obj['name']} (t1:{t1:.2f}s | t2:{t2:.2f}s)\n"
                sys.stdout.write(main_row)
                def fmt_range(key):
                    r = m.get(key, [0, 0])
                    return f"{r[0]:.2f} → {r[1]:.2f}s"
                sys.stdout.write(f"    \t🎙️ {fmt_range('stt')} | [{res_obj['stt_model']}] | Text: \"{m.get('stt_text', 'N/A')}\"\n")
                sys.stdout.write(f"    \t🧠 {fmt_range('llm')} | [{res_obj['llm_model']}] | Text: \"{m.get('llm_text', 'N/A').strip()}\"\n")
                sys.stdout.write(f"    \t🔊 {fmt_range('tts')} | [{res_obj['tts_model']}] | Path: {res_obj['result']}\n")
            else:
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
