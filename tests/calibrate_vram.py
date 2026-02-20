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

def calibrate_model(model_id):
    """
    Spawns vLLM for the given model, parses logs for VRAM metrics, and returns specs.
    """
    print(f"\n🚀 CALIBRATION START: {model_id}")
    print("-" * 50)

    # 1. Setup Manager (Force real mode, high util to ensure measurable surplus)
    # We use a safe high util (0.9) to get a clear reading of available surplus
    manager = LifecycleManager(
        setup_name="calibration", 
        models=[model_id], 
        purge_on_entry=True, 
        stub_mode=False,
        track_prior_vram=False
    )
    
    # Force override config for calibration accuracy
    manager.cfg['vllm']['gpu_memory_utilization'] = 0.90
    
    # 2. Reconcile (Start the container)
    try:
        # We don't want to wait for the full 'ready' health check if we can get logs earlier,
        # but reconcile handles the parallel wait.
        setup_time, _ = manager.reconcile(domain="llm")
        if setup_time == -1:
            print("❌ Model not found locally.")
            return
    except Exception as e:
        print(f"💥 Startup Error: {e}")
        manager.cleanup()
        return

    # 3. Monitor Logs
    # Find the log file created by LifecycleManager
    log_dir = manager.session_dir if manager.session_dir else os.path.join(project_root, "tests", "artifacts", "logs")
    # Get the latest svc_llm log
    log_files = [f for f in os.listdir(log_dir) if f.startswith("svc_llm") and f.endswith(".log")]
    if not log_files:
        print("❌ Could not find log file.")
        manager.cleanup()
        return
    
    log_path = os.path.join(log_dir, sorted(log_files)[-1])
    print(f"📝 Monitoring: {os.path.basename(log_path)}")

    # Regex Patterns
    re_base = re.compile(r"Model loading took ([\d\.]+) GiB memory")
    re_cache_gb = re.compile(r"Available KV cache memory: ([\d\.]+) GiB")
    re_tokens = re.compile(r"GPU KV cache size: ([\d,]+) tokens")

    base_vram = None
    cache_gb = None
    tokens = None

    start_wait = time.time()
    timeout = 600 # 10 mins for heavy models
    
    try:
        while time.time() - start_wait < timeout:
            if not os.path.exists(log_path):
                time.sleep(1); continue
                
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

    # 4. Calculate
    # We want gb_per_10k tokens with 4+ decimal places
    gb_per_10k = (cache_gb / tokens) * 10000
    
    result = {
        "base_vram_gb": round(base_vram, 4),
        "kv_cache_gb_per_10k": round(gb_per_10k, 6),
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_tokens": tokens,
        "source_cache_gb": cache_gb
    }

    # 5. Save to individual YAML
    specs_dir = os.path.join(project_root, "models", "specs")
    os.makedirs(specs_dir, exist_ok=True)
    
    # Sanitize filename
    safe_name = model_id.replace("/", "--").replace(":", "-").lower()
    file_path = os.path.join(specs_dir, f"{safe_name}.yaml")
    
    # Get GPU info for metadata
    gpu_info = utils.get_gpu_total_vram() # Or a more descriptive string if available
    
    output_data = {
        "id": model_id,
        "constants": {
            "base_vram_gb": round(base_vram, 4),
            "kv_cache_gb_per_10k": round(gb_per_10k, 6),
        },
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": gpu_info,
            "source_tokens": tokens,
            "source_cache_gb": cache_gb
        }
    }
    
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
    
    print(f"💾 Specification saved to: {os.path.relpath(file_path, project_root)}")

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
