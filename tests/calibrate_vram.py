import os
import sys
import time
import re
import json
import argparse
import yaml
import threading

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

import utils
from tests.test_utils.lifecycle import LifecycleManager

import shutil

def calibrate_model(model_id):
    """
    Spawns vLLM for the given model, parses logs for VRAM metrics, and returns specs.
    """
    print(f"\n🚀 CALIBRATION START: {model_id}")
    print("-" * 50)

    # 1. Create a unique session for this calibration to avoid log contamination
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(project_root, "tests", "logs", f"CALIBRATE_{timestamp}")
    os.makedirs(session_dir, exist_ok=True)

    # 2. Setup Manager (Force real mode)
    manager = LifecycleManager(
        setup_name="calibration", 
        models=[model_id], 
        purge_on_entry=True, 
        stub_mode=False,
        track_prior_vram=False,
        session_dir=session_dir
    )
    
    # Verify model presence first
    if not manager.check_availability():
        print(f"❌ Error: Model '{model_id}' not found in HF cache.")
        return

    # Force override config for calibration accuracy
    manager.cfg['vllm']['gpu_memory_utilization'] = 0.90
    
    # 3. Start the container
    try:
        # Reconcile will spawn the process and log to session_dir
        setup_time, _ = manager.reconcile(domain="llm")
        if setup_time == -1:
            print("❌ Reconcile failed.")
            return
    except Exception as e:
        print(f"💥 Startup Error: {e}")
        manager.cleanup()
        return

    # 4. Monitor the SPECIFIC log file for this run
    # Find the svc_llm log in our private session_dir
    log_files = [f for f in os.listdir(session_dir) if f.startswith("svc_llm") and f.endswith(".log")]
    if not log_files:
        print("❌ Could not find log file in session dir.")
        manager.cleanup()
        return
    
    log_path = os.path.join(session_dir, log_files[0])
    print(f"📝 Monitoring: {os.path.basename(log_path)}")

    # Regex Patterns
    re_base = re.compile(r"Model loading took ([\d\.]+) GiB memory")
    re_cache_gb = re.compile(r"Available KV cache memory: ([\d\.]+) GiB")
    re_tokens = re.compile(r"GPU KV cache size: ([\d,]+) tokens")

    base_vram = None
    cache_gb = None
    tokens = None

    start_wait = time.time()
    timeout = 600 # 10 mins
    
    try:
        while time.time() - start_wait < timeout:
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

            if base_vram and cache_gb and tokens:
                print("✅ All metrics captured.")
                break
            
            time.sleep(2)
    finally:
        manager.cleanup()

    if not (base_vram and cache_gb and tokens):
        print("❌ Calibration failed: Timeout or missing log entries.")
        return

    # 5. Calculate
    gb_per_10k = (cache_gb / tokens) * 10000
    
    output_data = {
        "id": model_id,
        "constants": {
            "base_vram_gb": round(base_vram, 4),
            "kv_cache_gb_per_10k": round(gb_per_10k, 6),
        },
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": utils.get_gpu_total_vram(),
            "source_tokens": tokens,
            "source_cache_gb": cache_gb
        }
    }

    # 6. Save Artifacts (YAML + Log)
    cal_dir = os.path.join(project_root, "models", "calibrations")
    os.makedirs(cal_dir, exist_ok=True)
    
    safe_name = model_id.replace("/", "--").replace(":", "-").lower()
    yaml_path = os.path.join(cal_dir, f"{safe_name}.yaml")
    dest_log_path = os.path.join(cal_dir, f"{safe_name}.log")
    
    # Save YAML
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
    
    # Save a copy of the log used for this calibration
    shutil.copy(log_path, dest_log_path)
    
    print(f"💾 Specification saved to: {os.path.relpath(yaml_path, project_root)}")
    print(f"💾 Reference log saved to: {os.path.relpath(dest_log_path, project_root)}")

    print("\n" + "="*50)
    print(f"CALIBRATION RESULT: {model_id}")
    print("-" * 50)
    print(yaml.dump(output_data))
    print("="*50)
    
    return output_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="vLLM VRAM & KV-Cache Calibrator")
    parser.add_argument("model", type=str, help="Model ID to calibrate")
    args = parser.parse_args()
    
    calibrate_model(args.model)
