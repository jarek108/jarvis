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
import utils
import test_utils

# Ensure UTF-8 output
utils.ensure_utf8_output()

def extract_frames(video_path, max_frames=8):
    frames = []
    try:
        container = av.open(video_path)
        video_stream = next(s for s in container.streams if s.type == 'video')
        total_frames = video_stream.frames
        if total_frames <= 0:
            duration = video_stream.duration if video_stream.duration else 0
            total_frames = int(duration * video_stream.time_base * video_stream.average_rate)
        if total_frames <= 0: total_frames = 300
        indices = np.linspace(0, total_frames - 1, max_frames, dtype=int)
        count = 0; decoded_count = 0
        for frame in container.decode(video_stream):
            if count in indices:
                img = frame.to_image(); img.thumbnail((512, 512))
                buffered = io.BytesIO(); img.save(buffered, format="JPEG")
                frames.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))
            count += 1; decoded_count += 1
            if len(frames) >= max_frames or decoded_count > total_frames + 1000: break
        container.close()
    except: pass
    return frames

def run_test_suite(model_name, scenarios_to_run=None, output_dir=None, reporter=None, **kwargs):
    cfg = utils.load_config()
    if not reporter:
        from test_utils.collectors import StdoutReporter
        reporter = StdoutReporter()

    input_base = os.path.join(os.path.dirname(__file__), "input_data")
    vram_baseline = utils.get_gpu_vram_usage()

    # Suffix logic
    native_video = kwargs.get('nativevideo', False)
    stream = kwargs.get('stream', False)
    
    mode_suffix = " [Stream]" if stream else " [Batch]"
    if native_video:
        mode_suffix = " [Native]" + mode_suffix

    is_vllm = model_name.startswith("VL_") or model_name.startswith("vllm:")
    if model_name.startswith("VL_"): clean_model_name = model_name[3:]
    elif model_name.startswith("vllm:"): clean_model_name = model_name[5:]
    elif model_name.startswith("OL_"): clean_model_name = model_name[3:]
    else: clean_model_name = model_name
    
    url = f"http://127.0.0.1:{cfg['ports']['vllm'] if is_vllm else cfg['ports']['ollama']}/v1/chat/completions" if is_vllm else f"http://127.0.0.1:{cfg['ports']['ollama']}/api/chat"

    for s in scenarios_to_run:
        file_path = os.path.join(input_base, s['media'])
        filename = s['media']

        # Initialize result object with metadata immediately
        res_obj = {
            "name": s['name'] + mode_suffix,
            "llm_model": model_name,
            "input_file": file_path,
            "input_text": s['text'],
            "streaming": stream,
            "mode": "VLM"
        }

        try:
            ext = os.path.splitext(filename)[1].lower()
            is_video = ext in [".mp4", ".mkv", ".avi", ".webm"]
            
            b64_frames = []
            if not (native_video and is_video):
                if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    with open(file_path, "rb") as bf: b64_frames = [base64.b64encode(bf.read()).decode('utf-8')]
                else:
                    b64_frames = extract_frames(file_path, max_frames=8)

            if is_vllm:
                content = [{"type": "text", "text": s['text']}]
                if native_video and is_video:
                    content.append({
                        "type": "video_url",
                        "video_url": {"url": f"file:///data/{filename}"}
                    })
                else:
                    content.extend([{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in b64_frames])
                
                payload = {"model": clean_model_name, "messages": [{"role": "user", "content": content}], "stream": stream, "temperature": 0}
            else:
                # Ollama doesn't support native video yet, fallback to slicing
                payload = {"model": clean_model_name, "messages": [{"role": "user", "content": s['text'], "images": b64_frames}], "stream": stream, "options": {"temperature": 0}}

            start_time = time.perf_counter(); first_token_time = None; full_text = ""; total_tokens = 0
            chunks = []; sentence_buffer = ""
            
            if stream:
                with requests.post(url, json=payload, stream=True) as resp:
                    if resp.status_code != 200:
                        res_obj.update({"status": "FAILED", "result": f"HTTP {resp.status_code}"})
                        reporter.report(res_obj)
                        continue
                    
                    for line in resp.iter_lines():
                        if line:
                            line_text = line.decode('utf-8').strip()
                            if is_vllm:
                                if not line_text.startswith("data: "): continue
                                data_str = line_text[6:]; 
                                if data_str == "[DONE]": break
                                token = json.loads(data_str)['choices'][0]['delta'].get('content', '')
                            else:
                                token = json.loads(line_text).get("message", {}).get("content", "")
                            if not token: continue
                            if first_token_time is None: first_token_time = time.perf_counter()
                            full_text += token; total_tokens += 1
                            sentence_buffer += token
                            if any(c in token for c in ".!?"):
                                chunks.append({"text": sentence_buffer.strip(), "end": time.perf_counter() - start_time})
                                sentence_buffer = ""

                if sentence_buffer.strip():
                    chunks.append({"text": sentence_buffer.strip(), "end": time.perf_counter() - start_time})
            else:
                # Non-streaming
                resp = requests.post(url, json=payload)
                if resp.status_code != 200:
                    res_obj.update({"status": "FAILED", "result": f"HTTP {resp.status_code}"})
                    reporter.report(res_obj)
                    continue
                
                data = resp.json()
                if is_vllm:
                    full_text = data['choices'][0]['message']['content']
                    total_tokens = data['usage']['completion_tokens']
                else:
                    full_text = data.get("message", {}).get("content", "")
                    total_tokens = data.get("eval_count", 0)
                
                # Simulate chunks for reporting
                chunks.append({"text": full_text, "end": time.perf_counter() - start_time})

            total_dur = time.perf_counter() - start_time
            ttft = (first_token_time - start_time) if first_token_time else total_dur
            res_obj.update({
                "status": "PASSED", "ttft": ttft, "tps": total_tokens / total_dur if total_dur > 0 else 0, 
                "text": full_text, "chunks": chunks, "duration": total_dur, 
                "vram_peak": utils.get_gpu_vram_usage(),
                "vram_prior": 0.0 # Will be injected by runner
            })
            reporter.report(res_obj)
        except Exception as e:
            res_obj.update({"status": "FAILED", "result": str(e)})
            reporter.report(res_obj)
        except Exception as e:
            res_obj.update({"status": "FAILED", "result": str(e)})
            reporter.report(res_obj)

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "scenarios.yaml"), "r") as f:
        all_scenarios = yaml.safe_load(f)
    scenarios = [{"name": k, **v} for k, v in all_scenarios.items()]
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--loadout", type=str, required=True)
    args = parser.parse_args()
    
    # Standalone support
    target_model = args.loadout 
    
    test_utils.run_test_lifecycle(
        domain="vlm", setup_name="manual", models=[target_model], 
        purge_on_entry=True, purge_on_exit=True, full=False, 
        test_func=lambda reporter=None: (
            run_test_suite(target_model, scenarios_to_run=scenarios, stream=False, reporter=reporter),
            run_test_suite(target_model, scenarios_to_run=scenarios, stream=True, reporter=reporter)
        )
    )
