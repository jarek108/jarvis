import os
import sys
import time
import re
import json
import argparse
import yaml
import threading
import shutil
import subprocess
import requests

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.append(project_root)

import utils
from tests.test_utils.lifecycle import LifecycleManager

def parse_ollama_size(size_str):
    """Converts '18.1 GiB' or '876.0 MiB' to float GB."""
    # Aggressive cleanup of the string
    size_str = size_str.strip().replace('"', '').replace('(', '').replace(')', '')
    m = re.match(r"([\d\.]+)\s*(\w+)i?B", size_str, re.IGNORECASE)
    if not m: return 0.0
    val, unit = float(m.group(1)), m.group(2).upper()
    if unit.startswith('M'): return val / 1024.0
    if unit.startswith('G'): return val
    if unit.startswith('K'): return val / (1024.0 * 1024.0)
    return val

def calibrate_vllm(model_id, project_root):
    """vLLM calibration logic using isolated session directory."""
    print(f"\n🚀 vLLM CALIBRATION START: {model_id}")
    print("-" * 50)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(project_root, "tests", "logs", f"CALIBRATE_vLLM_{timestamp}")
    os.makedirs(session_dir, exist_ok=True)

    manager = LifecycleManager(
        setup_name="calibration", 
        models=[model_id], 
        purge_on_entry=True, 
        stub_mode=False,
        track_prior_vram=False,
        session_dir=session_dir
    )
    
    if not manager.check_availability():
        print(f"❌ Error: Model '{model_id}' not found in local cache.")
        return

    # Force high util for calibration reading
    manager.cfg['vllm']['gpu_memory_utilization'] = 0.90
    
    try:
        setup_time, _ = manager.reconcile(domain="llm")
        if setup_time == -1: return
    except Exception as e:
        print(f"💥 Startup Error: {e}")
        manager.cleanup()
        return

    log_files = [f for f in os.listdir(session_dir) if f.startswith("svc_llm") and f.endswith(".log")]
    if not log_files:
        print("❌ Could not find log file.")
        manager.cleanup()
        return
    
    log_path = os.path.join(session_dir, log_files[0])
    re_base = re.compile(r"Model loading took ([\d\.]+) GiB memory")
    re_cache_gb = re.compile(r"Available KV cache memory: ([\d\.]+) GiB")
    re_tokens = re.compile(r"GPU KV cache size: ([\d,]+) tokens")

    base_vram, cache_gb, tokens = None, None, None
    start_wait = time.time()
    
    try:
        while time.time() - start_wait < 600:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if not base_vram:
                    m = re_base.search(content)
                    if m: base_vram = float(m.group(1)); print(f"  √ Base VRAM: {base_vram} GiB")
                if not cache_gb:
                    m = re_cache_gb.search(content)
                    if m: cache_gb = float(m.group(1)); print(f"  √ Cache Mem: {cache_gb} GiB")
                if not tokens:
                    m = re_tokens.search(content)
                    if m: 
                        tokens = int(m.group(1).replace(",", ""))
                        print(f"  √ KV Tokens: {tokens}")
            if base_vram and cache_gb and tokens: break
            time.sleep(2)
    finally:
        manager.cleanup()

    if not (base_vram and cache_gb and tokens): return
    gb_per_10k = (cache_gb / tokens) * 10000
    return save_calibration(model_id, "vllm", base_vram, gb_per_10k, tokens, cache_gb, log_path, project_root)

def calibrate_ollama(model_id, project_root):
    """Ollama calibration logic using logs exclusively for high precision."""
    print(f"\n🚀 OLLAMA CALIBRATION START: {model_id}")
    print("-" * 50)

    num_ctx = 32768
    print(f"⚙️ Target Context: {num_ctx}")

    print("🔄 Restarting Ollama...")
    utils.kill_jarvis_ports({11434})
    time.sleep(2)
    
    timestamp = int(time.time())
    session_log_path = os.path.join(project_root, "tests", "logs", f"ollama_session_{timestamp}.log")
    session_log_file = open(session_log_path, "w", encoding="utf-8")

    cfg = utils.load_config()
    ollama_models = os.environ.get("OLLAMA_MODELS", cfg.get("OLLAMA_MODELS"))
    env = os.environ.copy()
    if ollama_models: env["OLLAMA_MODELS"] = ollama_models

    proc = subprocess.Popen(["ollama", "serve"], creationflags=0x08000000, stdout=session_log_file, stderr=subprocess.STDOUT, env=env)
    if not utils.wait_for_port(11434, timeout=30):
        print("❌ Failed to start Ollama server."); session_log_file.close(); return

    print(f"🔥 Loading model: {model_id}...")
    payload = {"model": model_id, "prompt": "hi", "options": {"num_ctx": num_ctx}, "stream": False}
    def send_req():
        try: requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=300)
        except: pass
    threading.Thread(target=send_req, daemon=True).start()

    # Patterns
    re_total = re.compile(r'msg="total memory" size="?([^ "]+)"?')
    re_kv_log = re.compile(r'msg="kv cache" device=CUDA0 size="?([^ "]+)"?')
    re_tokens = re.compile(r'(?:llama_kv_cache: size|KV self size) = .*?\( +(\d+) cells')
    
    # Fallback/Summation patterns if 'total memory' is missing
    re_weight_vram = re.compile(r'msg="model weights" device=CUDA0 size="?([^ "]+)"?')
    re_compute_vram = re.compile(r'msg="compute graph" device=CUDA0 size="?([^ "]+)"?')

    total_gb, kv_gb, cells = None, None, None
    weight_gb, compute_gb = 0.0, 0.0
    
    print("⌛ Monitoring logs...")
    start_wait = time.time()
    while time.time() - start_wait < 300:
        with open(session_log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            if not total_gb:
                m = re_total.search(content)
                if m: total_gb = parse_ollama_size(m.group(1)); print(f"  √ Logged Total: {total_gb:.4f} GiB")
            if not kv_gb:
                m = re_kv_log.search(content)
                if m: kv_gb = parse_ollama_size(m.group(1)); print(f"  √ Logged KV: {kv_gb:.4f} GiB")
            if not cells:
                m = re_tokens.search(content)
                if m: cells = int(m.group(1)); print(f"  √ KV Tokens: {cells}")
            
            # Backups
            if not weight_gb:
                m = re_weight_vram.search(content)
                if m: weight_gb = parse_ollama_size(m.group(1))
            if not compute_gb:
                m = re_compute_vram.search(content)
                if m: compute_gb = parse_ollama_size(m.group(1))

        if (total_gb or (weight_gb and kv_gb)) and kv_gb and cells:
            if not total_gb: total_gb = weight_gb + kv_gb + compute_gb
            print("✅ Captured all metrics.")
            break
        time.sleep(2)

    if not (total_gb and kv_gb and cells):
        print("❌ Calibration failed."); return

    base_vram = total_gb - kv_gb
    gb_per_10k = (kv_gb / cells) * 10000
    return save_calibration(model_id, "ollama", base_vram, gb_per_10k, cells, kv_gb, session_log_path, project_root)

def save_calibration(model_id, engine, base_vram, gb_per_10k, source_tokens, source_cache_gb, log_source, project_root):
    cal_dir = os.path.join(project_root, "model_calibrations")
    os.makedirs(cal_dir, exist_ok=True)
    prefix = "ol_" if engine == "ollama" else "vl_"
    safe_name = prefix + model_id.replace("/", "--").replace(":", "-").lower()
    yaml_path = os.path.join(cal_dir, f"{safe_name}.yaml")
    dest_log_path = os.path.join(cal_dir, f"{safe_name}.log")
    
    output_data = {
        "id": model_id, "engine": engine,
        "constants": {"base_vram_gb": round(base_vram, 4), "kv_cache_gb_per_10k": round(gb_per_10k, 6)},
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": round(utils.get_gpu_total_vram(), 2),
            "source_tokens": source_tokens, "source_cache_gb": round(source_cache_gb, 4)
        }
    }
    with open(yaml_path, "w", encoding="utf-8") as f: yaml.dump(output_data, f, sort_keys=False)
    shutil.copy(log_source, dest_log_path)
    print(f"💾 Saved: {os.path.relpath(yaml_path, project_root)}")
    return output_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=str)
    parser.add_argument("--engine", choices=["vllm", "ollama"], default="vllm")
    args = parser.parse_args()
    if args.engine == "ollama": calibrate_ollama(args.model, project_root)
    else: calibrate_vllm(args.model, project_root)
