import requests
import os
import sys
import time
import json
import argparse
import yaml
import base64
import av
import numpy as np
import io
from PIL import Image

# Allow importing utils from parent levels
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import report_llm_result, ensure_utf8_output, run_test_lifecycle, get_gpu_vram_usage, check_ollama_offload, load_config

# Ensure UTF-8 output
ensure_utf8_output()

def extract_frames(video_path, max_frames=8):
    """Extracts evenly spaced frames from a video file using PyAV."""
    frames = []
    try:
        container = av.open(video_path)
        # Find video stream explicitly
        video_stream = next(s for s in container.streams if s.type == 'video')
        
        # Robust frame count estimation
        total_frames = video_stream.frames
        if total_frames <= 0:
            duration = video_stream.duration if video_stream.duration else 0
            time_base = video_stream.time_base if video_stream.time_base else 1
            rate = video_stream.average_rate if video_stream.average_rate else 30
            total_frames = int(duration * time_base * rate)
        
        if total_frames <= 0:
            total_frames = 300 # Fallback estimate for 10s @ 30fps
        
        indices = np.linspace(0, total_frames - 1, max_frames, dtype=int)
        
        count = 0
        decoded_count = 0
        for frame in container.decode(video_stream):
            if count in indices:
                img = frame.to_image()
                # Resize to save bandwidth/context
                img.thumbnail((512, 512))
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG")
                frames.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))
            
            count += 1
            decoded_count += 1
            if len(frames) >= max_frames or decoded_count > total_frames + 1000:
                break
        container.close()
    except Exception as e:
        print(f"Error extracting frames from {video_path}: {e}")
    return frames

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
    
    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    
    # Supported extensions
    IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
    VID_EXTS = (".mp4", ".mkv", ".avi", ".mov")
    
    # DISCOVERY: Find all files and look for matching .yaml
    scenarios = []
    all_files = os.listdir(input_base)
    for f in all_files:
        ext = os.path.splitext(f)[1].lower()
        name_base = os.path.splitext(f)[0]
        yaml_path = os.path.join(input_base, f"{name_base}.yaml")
        
        if not os.path.exists(yaml_path):
            continue

        with open(yaml_path, "r", encoding="utf-8") as yf:
            config = yaml.safe_load(yf)
            prompt = config.get("prompt", "")
            max_frames = config.get("max_frames", 8)

        if ext in IMG_EXTS:
            scenarios.append({
                "name": name_base,
                "text": prompt,
                "file": f,
                "type": "image"
            })
        elif ext in VID_EXTS:
            scenarios.append({
                "name": name_base,
                "text": prompt,
                "file": f,
                "type": "video",
                "max_frames": max_frames
            })

    if not scenarios:
        print(f"❌ ERROR: No valid VLM test cases found in {input_base}")
        return

    # Audit Start
    vram_baseline = get_gpu_vram_usage()

    for s in scenarios:
        try:
            file_path = os.path.join(input_base, s['file'])
            
            if s['type'] == "image":
                with open(file_path, "rb") as bf:
                    b64_frames = [base64.b64encode(bf.read()).decode('utf-8')]
            else:
                b64_frames = extract_frames(file_path, max_frames=s['max_frames'])

            if not b64_frames:
                report_llm_result({"name": s['name'], "status": "FAILED", "text": "Failed to load media frames.", "input_file": file_path, "input_text": s['text']})
                continue

            # Request construction
            if is_vllm:
                payload = {
                    "model": clean_model_name,
                    "messages": [{
                        "role": "user", 
                        "content": [
                            {"type": "text", "text": s['text']},
                            *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in b64_frames]
                        ]
                    }],
                    "stream": True,
                    "temperature": 0,
                    "seed": 42
                }
            else:
                payload = {
                    "model": clean_model_name,
                    "messages": [{
                        "role": "user", 
                        "content": s['text'],
                        "images": b64_frames
                    }],
                    "stream": True,
                    "options": {"temperature": 0, "seed": 42}
                }

            start_time = time.perf_counter()
            first_token_time = None
            full_text = ""
            total_tokens = 0

            with requests.post(url, json=payload, stream=True) as resp:
                if resp.status_code != 200:
                    report_llm_result({"name": s['name'], "status": "FAILED", "text": f"HTTP {resp.status_code}", "input_file": file_path, "input_text": s['text']})
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
                "ttfr": ttfr, 
                "tps": tps,
                "text": full_text,
                "duration": total_dur,
                "llm_model": model_name,
                "input_file": file_path,
                "input_text": s['text'],
                "vram_peak": get_gpu_vram_usage(),
                "streaming": True
            }
            report_llm_result(res_obj)

        except Exception as e:
            report_llm_result({"name": s['name'], "status": "FAILED", "text": str(e), "input_file": file_path, "input_text": s['text']})

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
    loadout_path = os.path.join(project_root, "loadouts", f"{args.loadout}.yaml")
    
    if not os.path.exists(loadout_path):
        print(f"❌ ERROR: Loadout '{args.loadout}' not found.")
        sys.exit(1)
        
    with open(loadout_path, "r") as f:
        l_data = yaml.safe_load(f)
        target_model = l_data.get('llm')
        if not target_model:
            print(f"❌ ERROR: Loadout '{args.loadout}' defines no LLM component for VLM testing.")
            sys.exit(1)

    # Standalone support
    run_test_lifecycle(
        domain="vlm",
        setup_name=args.loadout,
        models=[target_model],
        purge=args.purge,
        full=args.full,
        test_func=lambda: run_test_suite(target_model),
        benchmark_mode=args.benchmark_mode
    )
