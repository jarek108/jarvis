import os
import sys
import time
import argparse
import requests
import subprocess

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from tests.utils import (
    get_gpu_total_vram, stop_vllm_docker, wait_for_port, 
    start_server, get_service_status, load_config,
    kill_all_jarvis_services
)

# Results Categorization
STATUS_PASS = "Tests PASSED"
STATUS_NO_WAKE = "No wake up"
STATUS_CRASH = "Tests failed/crashed"

history = []

def run_stress_test(port):
    """Sends a medium-length prompt to verify KV cache stability."""
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload = {
        "model": "Qwen/Qwen2.5-0.5B-Instruct",
        "messages": [{"role": "user", "content": "Write a very long, detailed story about a space explorer. Repeat the word 'EXPLORE' 100 times to inflate the context."}],
        "max_tokens": 512,
        "temperature": 0
    }
    try:
        resp = requests.post(url, json=payload, timeout=60)
        return resp.status_code == 200
    except:
        return False

def test_allocation(gb, model_id):
    cfg = load_config()
    total_vram = get_gpu_total_vram()
    vllm_port = cfg['ports'].get('vllm', 8300)
    utilization = min(0.95, max(0.05, gb / total_vram))
    
    print(f"\n[Trial] Testing {gb:.2f} GB (Util: {utilization:.3f})...")
    
    # 1. Clean environment
    kill_all_jarvis_services()
    time.sleep(2)
    
    # 2. Start vLLM
    hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    cmd = [
        "docker", "run", "--gpus", "all", "-d", 
        "--name", "vllm-server", 
        "-p", f"{vllm_port}:8000", 
        "-v", f"{hf_cache}:/root/.cache/huggingface", 
        "vllm/vllm-openai", 
        "--model", model_id,
        "--gpu-memory-utilization", str(utilization)
    ]
    
    start_server(cmd)
    
    # 3. Wait for boot (300s timeout)
    print(f"  ... waiting for boot...", flush=True)
    start_time = time.time()
    off_count = 0
    boot_success = False
    
    while time.time() - start_time < 300:
        status, info = get_service_status(vllm_port)
        if status == "ON":
            boot_success = True
            break
        if status == "OFF":
            off_count += 1
            if off_count >= 2:
                print(f"  ❌ FAILED: Container exited/crashed (OFF status twice).")
                break
        else:
            off_count = 0 # Reset if we see STARTUP
            
        time.sleep(2)
    
    if not boot_success:
        print(f"  ❌ FAILED: {STATUS_NO_WAKE}")
        # Dump logs to see WHY
        res = subprocess.run(["docker", "logs", "vllm-server"], capture_output=True, text=True, encoding='utf-8', errors='replace')
        print("--- DOCKER LOGS ---")
        print(res.stdout[-1000:]) # Last 1000 chars
        print("-------------------")
        stop_vllm_docker()
        history.append({"gb": gb, "status": STATUS_NO_WAKE})
        return False
    
    # 4. Stress Test
    print(f"  🔥 Boot successful. Running stress test...")
    stress_success = run_stress_test(vllm_port)
    
    if stress_success:
        print(f"  ✅ {STATUS_PASS}")
        history.append({"gb": gb, "status": STATUS_PASS})
    else:
        print(f"  ❌ FAILED: {STATUS_CRASH}")
        history.append({"gb": gb, "status": STATUS_CRASH})
    
    stop_vllm_docker()
    return stress_success

def calibrate(model_id, min_gb, max_gb, precision=0.1):
    print(f"🚀 Starting VRAM Calibration for {model_id}")
    print(f"Target range: {min_gb}GB - {max_gb}GB | Precision: {precision}GB")
    
    # Initial Baseline Check
    print(f"\n--- BASELINE CHECK: {max_gb} GB ---")
    if not test_allocation(max_gb, model_id):
        print(f"❌ ERROR: Even the maximum allocation ({max_gb}GB) failed. Cannot calibrate.")
        return

    low = min_gb
    high = max_gb
    best_stable = max_gb
    
    while (high - low) > precision:
        mid = (low + high) / 2
        if test_allocation(mid, model_id):
            best_stable = mid
            high = mid 
        else:
            low = mid
            
    print("\n" + "="*80)
    print(f"{'CALIBRATION HISTORY':^80}")
    print("-" * 80)
    print(f"{'Memory Size':<20} | {'Result':<30}")
    print("-" * 80)
    # Sort history by memory size descending
    sorted_history = sorted(history, key=lambda x: x['gb'], reverse=True)
    for entry in sorted_history:
        print(f"{entry['gb']:>10.2f} GB        | {entry['status']}")
    
    print("-" * 80)
    print(f"Model: {model_id}")
    print(f"Absolute Breaking Point: ~{low:.2f} GB")
    print(f"Minimum Stable Allocation: {best_stable:.2f} GB")
    print(f"Recommended (with safety margin): {best_stable + 0.2:.2f} GB")
    print("="*80)

if __name__ == "__main__":
    # For now, hardcoded for the requested test
    calibrate("Qwen/Qwen2.5-0.5B-Instruct", 0.5, 4.0, 0.2)
