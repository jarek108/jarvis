import os
import sys
import json
import time
import subprocess
import requests
import argparse
from datetime import datetime

# Add project root to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.utils.config import load_config, resolve_path, get_hf_home
from tests.utils.infra import is_port_in_use, kill_process_on_port, start_server, wait_for_port, is_docker_daemon_running
from tests.utils.vram import get_gpu_total_vram, get_gpu_vram_usage

def run_calibration_step(model_name, util, max_len=32768):
    """Attempts to start vLLM with specific settings and returns success/failure."""
    port = 8300
    kill_process_on_port(port)
    
    hf_cache = get_hf_home()
    docker_name = "vllm-calibration"
    
    # Clean up previous calibration container
    subprocess.run(["docker", "rm", "-f", docker_name], capture_output=True)
    
    cmd = [
        "docker", "run", "--gpus", "all", "-d", 
        "--name", docker_name, 
        "-p", f"{port}:8000", 
        "-v", f"{hf_cache}:/root/.cache/huggingface", 
        "vllm/vllm-openai", 
        "--model", model_name,
        "--gpu-memory-utilization", f"{util:.3f}",
        "--max-model-len", str(max_len)
    ]
    
    start_time = time.time()
    print(f"  ↳ Testing Util: {util:.3f}, MaxLen: {max_len}... ", end="", flush=True)
    
    subprocess.run(cmd, capture_output=True)
    
    # Wait for port or failure
    success = False
    error_msg = ""
    timeout = 300
    
    while time.time() - start_time < timeout:
        # Check if container is still running
        res = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", docker_name], capture_output=True, text=True)
        if "false" in res.stdout:
            logs = subprocess.run(["docker", "logs", docker_name], capture_output=True, text=True)
            error_msg = "Engine failed to start. Check logs."
            if "ValueError" in logs.stdout:
                # Extract the specific ValueError message
                for line in logs.stdout.split('\n'):
                    if "ValueError:" in line:
                        error_msg = line.strip()
            break
            
        if is_port_in_use(port):
            try:
                resp = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=5)
                if resp.status_code == 200:
                    success = True
                    break
            except: pass
        time.sleep(5)
    
    # Cleanup
    subprocess.run(["docker", "rm", "-f", docker_name], capture_output=True)
    
    if success:
        print("✅ SUCCESS")
    else:
        print(f"❌ FAILED ({error_msg})")
        
    return success, error_msg, round(time.time() - start_time, 2)

def main():
    parser = argparse.ArgumentParser(description="Jarvis VRAM Calibration Tool")
    parser.add_argument("model", type=str, help="HuggingFace model ID")
    parser.add_argument("--max-len", type=int, default=32768)
    parser.add_argument("--step", type=float, default=0.05)
    args = parser.parse_args()

    if not is_docker_daemon_running():
        print("❌ Docker daemon is not running. Calibration aborted."); return

    total_vram = get_gpu_total_vram()
    model_safe_name = args.model.replace("/", "--").replace(":", "-")
    artifact_path = os.path.join("tests", "artifacts", "calibration", f"{model_safe_name}_trajectory.json")
    
    trajectory = {
        "model": args.model,
        "date": datetime.now().isoformat(),
        "gpu_total_vram_gb": total_vram,
        "max_model_len": args.max_len,
        "steps": []
    }

    print(f"🚀 Starting Calibration for {args.model}")
    print(f"📊 Total VRAM: {total_vram:.1f} GB")

    # Start at 0.1 and go up to 0.95
    current_util = 0.1
    best_util = None
    
    while current_util <= 0.95:
        success, error, duration = run_calibration_step(args.model, current_util, args.max_len)
        
        step_entry = {
            "utilization": round(current_util, 3),
            "vram_gb": round(current_util * total_vram, 2),
            "success": success,
            "error": error,
            "duration_s": duration
        }
        trajectory["steps"].append(step_entry)
        
        if success:
            best_util = current_util
            # If we found a success, we can stop or keep going to find the "ceiling"
            # For now, let's keep going to map the whole trajectory
        
        current_util += args.step

    # Final summary
    trajectory["best_utilization"] = best_util
    if best_util:
        trajectory["recommended_vram_gb"] = round(best_util * total_vram, 2)
        print(f"\n✅ CALIBRATION COMPLETE: Best utilization for {args.model} is {best_util:.3f} ({trajectory['recommended_vram_gb']} GB)")
    else:
        print(f"\n❌ CALIBRATION FAILED: No successful utilization found up to 0.95.")

    # Save artifact
    with open(artifact_path, "w") as f:
        json.dump(trajectory, f, indent=2)
    print(f"📁 Trajectory saved to {artifact_path}")

if __name__ == "__main__":
    main()
