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
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

import utils
from tests.test_utils.lifecycle import LifecycleManager

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
    print(f"📝 Monitoring: {os.path.basename(log_path)}")

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
    """Ollama calibration logic using server.log and VRAM probing."""
    print(f"\n🚀 OLLAMA CALIBRATION START: {model_id}")
    print("-" * 50)

    # 1. Configuration
    num_ctx = 32768
    print(f"⚙️ Target Context: {num_ctx}")

    # 2. Restart Ollama to clear VRAM and ensure clean logs
    print("🔄 Restarting Ollama...")
    utils.kill_jarvis_ports({11434})
    time.sleep(2)
    
    # Crucial: Use the correct models path from env or config
    cfg = utils.load_config()
    ollama_models = os.environ.get("OLLAMA_MODELS", cfg.get("OLLAMA_MODELS"))
    env = os.environ.copy()
    if ollama_models:
        env["OLLAMA_MODELS"] = ollama_models
        print(f"📁 Using OLLAMA_MODELS: {ollama_models}")

    # Start Ollama natively and capture its output
    timestamp = int(time.time())
    session_log_path = os.path.join(project_root, "tests", "logs", f"ollama_session_{timestamp}.log")
    session_log_file = open(session_log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        ["ollama", "serve"], 
        creationflags=0x08000000, 
        stdout=session_log_file, 
        stderr=subprocess.STDOUT,
        env=env
    )
    
    if not utils.wait_for_port(11434, timeout=30):
        print("❌ Failed to start Ollama server.")
        session_log_file.close()
        return

    # 3. Use the session log for monitoring
    log_path = session_log_path
    initial_log_size = 0
    
    # 4. Trigger Model Load
    print(f"🔥 Loading model: {model_id}...")
    payload = {"model": model_id, "prompt": "hi", "options": {"num_ctx": num_ctx}, "stream": False}
    
    peak_vram = 0.0
    def send_req():
        try: requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=300)
        except: pass

    req_thread = threading.Thread(target=send_req)
    req_thread.start()

    # 5. Measure Peak VRAM during load
    # Matches: "llama_kv_cache: size =  384.00 MiB" or "KV self size = 1792.00 MiB"
    re_kv = re.compile(r"(?:llama_kv_cache: size|KV self size) = +([\d\.]+) MiB")
    # Matches: "load_hparams: model size:         867.61 MiB"
    re_model_size = re.compile(r"model size: +([\d\.]+) MiB")
    
    kv_mib = None
    log_model_mib = None
    
    print("⌛ Monitoring logs and VRAM (this may take a minute)...")
    start_wait = time.time()
    while time.time() - start_wait < 300:
        current_vram = utils.get_gpu_vram_usage()
        if current_vram > peak_vram:
            peak_vram = current_vram
        
        # Check logs for KV size
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(initial_log_size)
                new_content = f.read()
                
                if "size =" in new_content or "KV self size =" in new_content:
                    m = re_kv.search(new_content)
                    if m:
                        kv_mib = float(m.group(1))
                        print(f"  √ Logged KV Size: {kv_mib} MiB")
                
                if "model size:" in new_content:
                    m = re_model_size.search(new_content)
                    if m:
                        log_model_mib = float(m.group(1))
                        print(f"  √ Logged Model Size: {log_model_mib} MiB")
        
        if kv_mib and peak_vram > (current_vram - 0.1): # Wait for VRAM to stabilize
             if peak_vram > 0:
                print(f"  √ Measured Peak VRAM: {peak_vram:.2f} GiB")
                break
        
        if not req_thread.is_alive() and not kv_mib:
            print("⚠️ Request thread finished without capturing KV size. Retrying log read...")
            # One last check of the full log
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(initial_log_size)
                m = re_kv.search(f.read())
                if m:
                    kv_mib = float(m.group(1))
                    print(f"  √ Logged KV Size (Final Catch): {kv_mib} MiB")
                    break
            break

        time.sleep(1)

    req_thread.join()
    
    if not (kv_mib and peak_vram):
        print("❌ Calibration failed: Could not capture KV size or VRAM peak.")
        # Debug: Print the last few lines of the log we were watching
        print("\n🔍 LOG TAIL FOR DEBUGGING:")
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            print("".join(f.readlines()[-20:]))
        return

    # 6. Calculate
    kv_gb = kv_mib / 1024.0
    base_vram = peak_vram - kv_gb
    gb_per_10k = (kv_gb / num_ctx) * 10000

    # For the reference log, we capture the last 100 lines of server.log
    temp_log = os.path.join(project_root, "tests", "logs", f"ollama_cal_snippet_{int(time.time())}.log")
    with open(log_path, "r", encoding="utf-8", errors="ignore") as src, open(temp_log, "w", encoding="utf-8") as dest:
        dest.writelines(src.readlines()[-100:])

    return save_calibration(model_id, "ollama", base_vram, gb_per_10k, num_ctx, kv_gb, temp_log, project_root)

def save_calibration(model_id, engine, base_vram, gb_per_10k, source_tokens, source_cache_gb, log_source, project_root):
    """Unified artifact saving logic."""
    cal_dir = os.path.join(project_root, "models", "calibrations")
    os.makedirs(cal_dir, exist_ok=True)
    
    prefix = "ol_" if engine == "ollama" else "vl_"
    safe_name = prefix + model_id.replace("/", "--").replace(":", "-").lower()
    yaml_path = os.path.join(cal_dir, f"{safe_name}.yaml")
    dest_log_path = os.path.join(cal_dir, f"{safe_name}.log")
    
    output_data = {
        "id": model_id,
        "engine": engine,
        "constants": {
            "base_vram_gb": round(base_vram, 4),
            "kv_cache_gb_per_10k": round(gb_per_10k, 6),
        },
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": utils.get_gpu_total_vram(),
            "source_tokens": source_tokens,
            "source_cache_gb": round(source_cache_gb, 4)
        }
    }
    
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
    
    shutil.copy(log_source, dest_log_path)
    
    print(f"💾 Specification saved to: {os.path.relpath(yaml_path, project_root)}")
    print(f"💾 Reference log saved to: {os.path.relpath(dest_log_path, project_root)}")
    
    print("\n" + "="*50)
    print(f"CALIBRATION RESULT ({engine.upper()}): {model_id}")
    print("-" * 50)
    print(yaml.dump(output_data))
    print("="*50)
    return output_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis VRAM & KV-Cache Calibrator")
    parser.add_argument("model", type=str, help="Model ID to calibrate")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"], default="vllm", help="Inference engine")
    args = parser.parse_args()
    
    if args.engine == "ollama":
        calibrate_ollama(args.model, project_root)
    else:
        calibrate_vllm(args.model, project_root)
