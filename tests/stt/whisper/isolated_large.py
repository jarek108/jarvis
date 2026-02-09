import subprocess
import os
import sys
import yaml
import time
import json
import io
from contextlib import redirect_stdout

# Allow importing utils from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import get_service_status, wait_for_port, kill_process_on_port, load_config, start_server

# ANSI Colors
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

class LiveFilter(io.StringIO):
    """Captures everything, but only writes non-JSON lines to the real stdout."""
    def write(self, s):
        for line in s.splitlines(keepends=True):
            if not line.startswith("SCENARIO_RESULT: "):
                sys.__stdout__.write(line)
                sys.__stdout__.flush()
        return super().write(s)

def test_isolated():
    cfg = load_config()
    target_id = "faster-whisper-large"
    port = cfg['stt_loadout'][target_id]
    
    # Absolute paths logic
    tests_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    project_root = os.path.dirname(tests_root)
    python_exe = os.path.join(project_root, "jarvis-venv", "Scripts", "python.exe")
    server_script = os.path.join(project_root, "servers", "stt_server.py")

    print(f"\n--- SMART STT {target_id.upper()} LIFECYCLE (Port {port}) ---")
    
    # 1. Setup
    status = get_service_status(port)
    setup_start = time.perf_counter()
    started_here = False
    
    if status == "ON":
        print(f"INFO: Service already healthy. Skipping setup.")
        setup_time = 0
    else:
        if status == "UNHEALTHY":
            print(f"WARN: Service unhealthy. Cleaning port...")
            kill_process_on_port(port)
        
        print(f"STARTING STT Server (Quietly)...")
        cmd = [python_exe, server_script, "--port", str(port), "--model", target_id]
        process = start_server(cmd, loud=False)
        started_here = True
        if not wait_for_port(port, timeout=600, process=process):
            print("FAILED: Server failed to start.")
            return
        setup_time = time.perf_counter() - setup_start

    # 2. Processing (Run tests with Live Filter)
    from tests import run_test
    
    LINE_LEN = 120
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{'STT ISOLATED TEST: ' + target_id.upper():^120}{RESET}")
    print("="*LINE_LEN)
    
    f = LiveFilter()
    proc_start = time.perf_counter()
    with redirect_stdout(f):
        run_test(model_id=target_id)
    proc_time = time.perf_counter() - proc_start
    
    # Extract scenarios from captured machine output
    output = f.getvalue()
    scenarios = []
    for line in output.splitlines():
        if line.startswith("SCENARIO_RESULT: "):
            scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))

    # 3. Cleanup
    cleanup_start = time.perf_counter()
    if started_here:
        print(f"\nCleaning up {target_id.upper()} STT Server...")
        kill_process_on_port(port)
    else:
        print(f"\nINFO: Skipping cleanup (Service was already running).")
    cleanup_time = time.perf_counter() - cleanup_start

    print("="*LINE_LEN)
    time_str = f"Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s"
    print(f"{BOLD}Final Receipt:{RESET} {time_str}")
    print("="*LINE_LEN + "\n")

    receipt = {"setup": setup_time, "processing": proc_time, "cleanup": cleanup_time}
    print(f"LIFECYCLE_RECEIPT: {json.dumps(receipt)}")

if __name__ == "__main__":
    test_isolated()
