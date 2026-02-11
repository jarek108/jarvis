import requests
import os
import sys
import time
import json
import argparse
import yaml
import base64

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import report_llm_result, ensure_utf8_output, run_test_lifecycle, get_gpu_vram_usage, check_ollama_offload

# Ensure UTF-8 output
ensure_utf8_output()

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def run_test_suite(model_name):
    url = "http://127.0.0.1:11434/api/chat"
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    
    scenarios = [
        {
            "name": "vlm_object_id",
            "text": "What is in this image?",
            "image": "jarvis_logo.png"
        },
        {
            "name": "vlm_count",
            "text": "How many colored circles do you see in this photo?",
            "image": "three_objects.png"
        }
    ]

    # Audit Start
    vram_baseline = get_gpu_vram_usage()

    for s in scenarios:
        image_path = os.path.join(input_base, s['image'])
        if not os.path.exists(image_path):
            report_llm_result({"name": s['name'], "status": "FAILED", "text": f"Image missing: {s['image']}"})
            continue

        img_b64 = encode_image(image_path)
        
        payload = {
            "model": model_name,
            "messages": [{
                "role": "user", 
                "content": s['text'],
                "images": [img_b64]
            }],
            "stream": True,
            "options": {"temperature": 0, "seed": 42}
        }

        try:
            start_time = time.perf_counter()
            first_token_time = None
            full_text = ""
            total_tokens = 0

            with requests.post(url, json=payload, stream=True) as resp:
                if resp.status_code != 200:
                    report_llm_result({"name": s['name'], "status": "FAILED", "text": f"HTTP {resp.status_code}"})
                    continue

                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line.decode())
                        token = data.get("message", {}).get("content", "")
                        
                        if first_token_time is None and token.strip():
                            first_token_time = time.perf_counter()

                        full_text += token
                        total_tokens += 1

            total_dur = time.perf_counter() - start_time
            ttft = (first_token_time - start_time) if first_token_time else 0
            tps = total_tokens / total_dur if total_dur > 0 else 0

            res_obj = {
                "name": s['name'],
                "status": "PASSED",
                "ttft": ttft,
                "ttfr": ttft, # Same for VLM in this simplified reporter
                "tps": tps,
                "text": full_text,
                "duration": total_dur
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
    print(f"VRAM FOOTPRINT (VLM): {model_name.upper()}")
    print(f"  Peak: {vram_peak:.1f} GB")
    print("-" * 40 + "\n")
    print(f"VRAM_AUDIT_RESULT: {json.dumps(audit_data)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis VLM Test Suite")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout YAML name")
    parser.add_argument("--purge", action="store_true", help="Kill extra Jarvis services")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()

    # Load loadout
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
            print(f"❌ ERROR: Loadout '{args.loadout}' defines no LLM component for VLM testing.")
            sys.exit(1)

    run_test_lifecycle(
        domain="vlm",
        loadout_name=args.loadout,
        purge=args.purge,
        full=args.full,
        test_func=lambda: run_test_suite(target_model),
        benchmark_mode=args.benchmark_mode
    )
