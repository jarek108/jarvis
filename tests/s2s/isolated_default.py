import subprocess
import os
import sys
import yaml
import time
import json
import io
from contextlib import redirect_stdout
import re
import threading

# Force UTF-8 for console output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Allow importing utils from current directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import get_service_status, wait_for_port, kill_process_on_port, load_config, start_server
from tests import run_test

# ANSI Colors
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"
GRAY = "\033[90m"

class LiveFilter(io.StringIO):
    """Captures everything, but only writes non-JSON lines to the real stdout."""
    def __init__(self):
        super().__init__()
        if sys.platform == "win32":
            # Re-wrap __stdout__ to ensure it handles utf-8
            self.out = io.TextIOWrapper(sys.__stdout__.buffer, encoding='utf-8')
        else:
            self.out = sys.__stdout__

    def write(self, s):
        for line in s.splitlines(keepends=True):
            is_machine = line.startswith("SCENARIO_RESULT: ")
            # Write human lines always, write machine lines only if captured (not a tty)
            if not is_machine or not self.out.isatty():
                self.out.write(line)
                self.out.flush()
        return super().write(s)

def stream_logs(pipe, prefix):
    # Regex to strip Loguru metadata and ANSI codes
    log_pattern = re.compile(r".*?[A-Z]+\s+\| (.*)$")
    ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])')
    
    for line in iter(pipe.readline, ''):
        if line:
            clean_line = line.strip()
            match = log_pattern.match(ansi_escape.sub('', clean_line))
            if match:
                display_msg = match.group(1)
                print(f"  {GRAY}s2s ➔{RESET} {display_msg}")
            else:
                if "INFO:" in clean_line: continue
                print(f"  {GRAY}{prefix}{RESET} {clean_line}")
    pipe.close()

def test_isolated():
    loadout_name = "default"
    cfg = load_config()
    port = cfg['ports']['s2s']
    
    # Resolve loadout to find ports for cleanup
    tests_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(tests_root)
    loadout_path = os.path.join(tests_root, "loadouts", f"{loadout_name}.yaml")
    
    active_stt = None
    active_tts = None
    if os.path.exists(loadout_path):
        with open(loadout_path, "r") as f:
            l_data = yaml.safe_load(f)
            active_stt = l_data.get("stt", [None])[0]
            active_tts = l_data.get("tts", [None])[0]
    
    stt_port = cfg['stt_loadout'].get(active_stt) if active_stt else None
    tts_port = cfg['tts_loadout'].get(active_tts) if active_tts else None

    # Absolute paths logic
    python_exe = os.path.join(project_root, "jarvis-venv", "Scripts", "python.exe")
    server_script = os.path.join(project_root, "servers", "s2s_server.py")
    
    print(f"\n--- SMART S2S {loadout_name.upper()} LIFECYCLE (Port {port}) ---")
    
    # 1. Setup
    status = get_service_status(port)
    setup_start = time.perf_counter()
    started_here = False
    
    if status == "ON":
        print(f"INFO: S2S Server already healthy. Skipping setup.")
        setup_time = 0
    else:
        if status == "UNHEALTHY":
            print(f"WARN: S2S Server unhealthy. Cleaning ports...")
            kill_process_on_port(port)
            if stt_port: kill_process_on_port(stt_port)
            if tts_port: kill_process_on_port(tts_port)
        
        print(f"STARTING S2S Server with loadout: {loadout_name}...")
        cmd = [python_exe, server_script, "--loadout", loadout_name]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1,
            creationflags=0x08000000 if os.name == 'nt' else 0 
        )
        started_here = True
        
        log_thread = threading.Thread(target=stream_logs, args=(process.stdout, "[S2S]"), daemon=True)
        log_thread.start()

        if not wait_for_port(port, timeout=120):
            print("FAILED: S2S Server failed to initialize within timeout.")
            return
            
        setup_time = time.perf_counter() - setup_start

    # 2. Processing
    LINE_LEN = 120
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{'S2S ISOLATED PIPELINE TEST: ' + loadout_name.upper():^120}{RESET}")
    print("="*LINE_LEN)
    
    f = LiveFilter()
    proc_start = time.perf_counter()
    with redirect_stdout(f):
        run_test(skip_health=True, loadout_id=loadout_name)
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
        print(f"\nCleaning up S2S Server (all active ports)...")
        kill_process_on_port(port)
        if stt_port: kill_process_on_port(stt_port)
        if tts_port: kill_process_on_port(tts_port)
    else:
        print(f"\nINFO: Skipping cleanup (Service was already running).")
    cleanup_time = time.perf_counter() - cleanup_start

    print("="*LINE_LEN)
    time_str = f"Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s"
    print(f"{BOLD}Final Receipt:{RESET} {time_str}")
    print("="*LINE_LEN + "\n")

    receipt = {
        "setup": setup_time,
        "processing": proc_time,
        "cleanup": cleanup_time
    }
    # Ensure this goes to the same stream LiveFilter uses
    final_out = io.TextIOWrapper(sys.__stdout__.buffer, encoding='utf-8') if sys.platform == "win32" else sys.__stdout__
    final_out.write(f"LIFECYCLE_RECEIPT: {json.dumps(receipt)}\n")
    final_out.flush()

if __name__ == "__main__":
    test_isolated()
