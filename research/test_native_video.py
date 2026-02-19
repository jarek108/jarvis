import subprocess
import time
import os
import requests
import sys
import json

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils

MODEL_ID = "QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ"
CONTAINER_NAME = "vllm-video-probe"
PORT = 8300
VIDEO_DIR = os.path.join(os.getcwd(), "tests", "vlm", "input_data")
VIDEO_FILE = "bunny.mp4"

def start_vllm():
    hf_cache = os.environ.get("HF_HOME")
    if not hf_cache:
        print("❌ HF_HOME not set")
        return False

    # Kill existing if any
    subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True)
    subprocess.run(["docker", "rm", CONTAINER_NAME], capture_output=True)

    print(f"🚀 Starting vLLM with {MODEL_ID}...")
    
    # Correct format for --limit-mm-per-prompt is a JSON string
    mm_limit = json.dumps({"image": 1, "video": 1})
    
    cmd = [
        "docker", "run", "--gpus", "all", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{PORT}:8000",
        "-v", f"{hf_cache}:/root/.cache/huggingface",
        "-v", f"{VIDEO_DIR}:/data",
        "vllm/vllm-openai",
        MODEL_ID,  # Positional argument
        "--allowed-local-media-path", "/data",
        "--limit-mm-per-prompt", mm_limit,
        "--max-model-len", "8192",
        "--gpu-memory-utilization", "0.8"
    ]
    
    subprocess.run(cmd, check=True)
    
    # Wait for health check
    print("⌛ Waiting for vLLM to become ready (this can take 1-2 mins)...")
    start_time = time.time()
    timeout = 600 # 10 mins
    while time.time() - start_time < timeout:
        try:
            resp = requests.get(f"http://127.0.0.1:{PORT}/v1/models")
            if resp.status_code == 200:
                print(f"✅ vLLM is ONLINE ({time.time() - start_time:.1f}s)")
                return True
        except:
            pass
        # Output heartbeat to prevent tool timeout
        print(f"  ... {int(time.time() - start_time)}s elapsed")
        time.sleep(10)
    
    print("❌ vLLM Startup Timeout")
    return False

def run_probe():
    print("🎬 Running Native Video Probe...")
    video_url = f"file:///data/{VIDEO_FILE}"
    
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from vllm_video_probe import probe_video
    success = probe_video(f"http://127.0.0.1:{PORT}", MODEL_ID, video_url)
    return success

def cleanup():
    print("🧹 Cleaning up container...")
    subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True)
    subprocess.run(["docker", "rm", CONTAINER_NAME], capture_output=True)

if __name__ == "__main__":
    try:
        if start_vllm():
            run_probe()
    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"💥 Error: {e}")
    finally:
        cleanup()
