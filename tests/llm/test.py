import requests
import os
import sys
import time
import json
import argparse
import yaml

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import report_llm_result, ensure_utf8_output, run_test_lifecycle, get_gpu_vram_usage, check_ollama_offload, load_config

# Ensure UTF-8 output
ensure_utf8_output()

def run_test_suite(model_name, scenarios_to_run=None, output_dir=None):
    cfg = load_config()
    is_vllm = model_name.startswith("VL_") or model_name.startswith("vllm:")
    if model_name.startswith("VL_"): clean_model_name = model_name[3:]
    elif model_name.startswith("vllm:"): clean_model_name = model_name[5:]
    elif model_name.startswith("OL_"): clean_model_name = model_name[3:]
    else: clean_model_name = model_name
    
    url = f"http://127.0.0.1:{cfg['ports']['vllm'] if is_vllm else cfg['ports']['ollama']}/v1/chat/completions" if is_vllm else f"http://127.0.0.1:{cfg['ports']['ollama']}/api/chat"
    
    # Audit Start
    vram_baseline = get_gpu_vram_usage()

    for s in scenarios_to_run:
        if is_vllm:
            payload = {
                "model": clean_model_name,
                "messages": [{"role": "user", "content": s['text']}],
                "stream": True,
                "temperature": 0,
                "seed": 42
            }
        else:
            payload = {
                "model": clean_model_name,
                "messages": [{"role": "user", "content": s['text']}],
                "stream": True,
                "options": {"temperature": 0, "seed": 42}
            }

        try:
            start_time = time.perf_counter()
            first_token_time = None
            first_response_time = None
            full_text = ""
            thought_text = ""
            chunks = []
            sentence_buffer = ""
            total_tokens = 0
            is_thinking = False

            with requests.post(url, json=payload, stream=True) as resp:
                if resp.status_code != 200:
                    report_llm_result({"name": s['name'], "status": "FAILED", "text": f"HTTP {resp.status_code}"})
                    continue

                for line in resp.iter_lines():
                    if line:
                        line_text = line.decode('utf-8').strip()
                        if is_vllm:
                            if not line_text.startswith("data: "): continue
                            data_str = line_text[6:]
                            if data_str == "[DONE]": break
                            data = json.loads(data_str)
                            token = data['choices'][0]['delta'].get('content', '')
                        else:
                            data = json.loads(line_text)
                            token = data.get("message", {}).get("content", "")
                        
                        if not token: continue

                        if first_token_time is None:
                            first_token_time = time.perf_counter()

                        if "<thought>" in token: 
                            is_thinking = True
                            continue
                        if "</thought>" in token: 
                            is_thinking = False
                            continue
                        
                        if is_thinking:
                            thought_text += token
                        else:
                            full_text += token
                            sentence_buffer += token
                            if first_response_time is None and token.strip():
                                first_response_time = time.perf_counter()

                            if any(c in token for c in ".!?"):
                                chunks.append({
                                    "text": sentence_buffer.strip(),
                                    "end": time.perf_counter() - start_time
                                })
                                sentence_buffer = ""

                        total_tokens += 1

                if sentence_buffer.strip():
                    chunks.append({
                        "text": sentence_buffer.strip(),
                        "end": time.perf_counter() - start_time
                    })

            total_dur = time.perf_counter() - start_time
            ttft = (first_token_time - start_time) if first_token_time else 0
            tps = total_tokens / total_dur if total_dur > 0 else 0

            res_obj = {
                "name": s['name'],
                "status": "PASSED",
                "ttft": ttft,
                "tps": tps,
                "raw_text": full_text,
                "thought": thought_text.strip(),
                "chunks": chunks,
                "duration": total_dur,
                "llm_model": model_name,
                "input_text": s['text'],
                "streaming": True,
                "vram_peak": get_gpu_vram_usage(),
                "vram_prior": 0.0 # Will be injected by runner
            }
            report_llm_result(res_obj)

        except Exception as e:
            report_llm_result({"name": s['name'], "status": "FAILED", "text": str(e)})

    # Audit End
    vram_peak = get_gpu_vram_usage()
    is_ok, vram_used, total_size = check_ollama_offload(model_name)
    
    audit_data = {
        "model": model_name,
        "baseline_gb": vram_baseline,
        "peak_gb": vram_peak,
        "is_ok": is_ok,
        "vram_used_gb": vram_used,
        "total_size_gb": total_size
    }
    
    print("\n" + "-"*40)
    print(f"VRAM FOOTPRINT: {model_name.upper()}")
    print(f"  Baseline: {vram_baseline:.1f} GB")
    print(f"  Peak:     {vram_peak:.1f} GB")
    if total_size > 0:
        status_txt = "FULL VRAM" if is_ok else "🚨 RAM SWAP"
        print(f"  Placement: {status_txt} ({vram_used:.1f}GB / {total_size:.1f}GB)")
    print("-"*40 + "\n")
    print(f"VRAM_AUDIT_RESULT: {json.dumps(audit_data)}")

if __name__ == "__main__":
    # Standalone support
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "scenarios.yaml"), "r") as f:
        data = yaml.safe_load(f)
    scenarios = [{"name": k, **v} for k, v in data.items()]

    parser = argparse.ArgumentParser()
    parser.add_argument("--loadout", type=str, required=True)
    args = parser.parse_args()

    cfg = load_config()
    l_path = os.path.join(os.path.dirname(script_dir), "loadouts", f"{args.loadout}.yaml")
    with open(l_path, "r") as f:
        target_model = yaml.safe_load(f).get('llm')

    run_test_lifecycle(
        domain="llm", setup_name=args.loadout, models=[target_model],
        purge_on_entry=True, purge_on_exit=True, full=False,
        test_func=lambda: run_test_suite(target_model, scenarios_to_run=scenarios)
    )
