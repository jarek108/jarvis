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

def run_test_suite(model_name):
    cfg = load_config()
    is_vllm = False
    clean_model_name = model_name
    
    if model_name.startswith("vl_") or model_name.startswith("vllm:"):
        is_vllm = True
        clean_model_name = model_name[3:] if model_name.startswith("vl_") else model_name[5:]
        url = f"http://127.0.0.1:{cfg['ports']['vllm']}/v1/chat/completions"
    else:
        # Default to Ollama native API
        if model_name.startswith("ol_"):
            clean_model_name = model_name[3:]
        url = f"http://127.0.0.1:{cfg['ports']['ollama']}/api/chat"
    
    scenarios = [
        {"name": "english_std", "text": "Hello, this is a test of Tatterbox TTS."},
        {"name": "polish_explicit", "text": "Cześć, nazywam się Jarbis, jed mogę ci dzisiaj pomóc."},
        {"name": "short2long", "text": "Tell me a four to five sentences story about a dog."},
        {"name": "long2short", "text": "It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife. However little known the feelings or views of such a man may be on his first entering a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is considered the rightful property of some one or other of their daughters. What is the title of this book? Respond with title only."}
    ]

    # Audit Start
    vram_baseline = get_gpu_vram_usage()

    for s in scenarios:
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
            ttft = first_token_time - start_time if first_token_time else 0
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
                "llm_model": model_name
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
    
    # Unified output for LLM Audit
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
    parser = argparse.ArgumentParser(description="Jarvis LLM Test Suite")
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
        target_model = l_data.get('llm')
        if not target_model:
            print(f"❌ ERROR: Loadout '{args.loadout}' defines no LLM component.")
            sys.exit(1)

    # Standalone support
    run_test_lifecycle(
        domain="llm",
        setup_name=args.loadout,
        models=[target_model],
        purge=args.purge,
        full=args.full,
        test_func=lambda: run_test_suite(target_model),
        benchmark_mode=args.benchmark_mode
    )
