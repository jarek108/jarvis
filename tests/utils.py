import socket
import time
import psutil
import yaml
import os
import requests
import subprocess
import json
import io
import sys
from loguru import logger

# --- SHARED UI CONSTANTS ---
CYAN = "\033[96m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
LINE_LEN = 120

def ensure_utf8_output():
    """Forces UTF-8 for console output on Windows to prevent UnicodeEncodeErrors."""
    if sys.platform == "win32":
        if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        if not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class LiveFilter(io.StringIO):
    """Captures everything, but only writes non-machine lines to the real stdout in TTY mode."""
    def __init__(self):
        super().__init__()
        ensure_utf8_output()
        # self.out is already sys.stdout (potentially re-wrapped by ensure_utf8_output)
        self.out = sys.stdout

    def write(self, s):
        for line in s.splitlines(keepends=True):
            is_machine = line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ")
            # Always write human lines. Only write machine lines if captured (not a TTY).
            if not is_machine or not self.out.isatty():
                self.out.write(line)
                self.out.flush()
        return super().write(s)

def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_service_status(port: int):
    if not is_port_in_use(port): return "OFF"
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == 11434: url = f"http://127.0.0.1:{port}/api/tags"
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            return "BUSY" if response.json().get("status") == "busy" else "ON"
        elif response.status_code == 503 and response.json().get("status") == "STARTUP":
            return "STARTUP"
        return "UNHEALTHY"
    except:
        return "UNHEALTHY"

def get_system_health():
    cfg = load_config()
    health = {}
    ollama_status = get_service_status(cfg['ports']['llm'])
    health["Ollama"] = {"status": ollama_status, "port": cfg['ports']['llm']}
    for name, port in cfg['stt_loadout'].items():
        health[f"STT-{name}"] = {"status": get_service_status(port), "port": port}
    for name, port in cfg['tts_loadout'].items():
        health[f"TTS-{name}"] = {"status": get_service_status(port), "port": port}
    return health

def start_server(cmd, loud=False):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    final_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd]) if isinstance(cmd, list) else cmd
    
    # Resolve project root (one level up from tests/utils.py)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return subprocess.Popen(final_cmd, creationflags=flags, shell=True, cwd=project_root)

def wait_for_port(port: int, timeout: int = 60, process=None) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        if get_service_status(port) == "ON": return True
        if process and process.poll() is not None: return False
        time.sleep(1)
    return False

def kill_process_on_port(port: int):
    try:
        if port == 11434 and os.name == 'nt':
            os.system("taskkill /F /IM ollama* /T > nul 2>&1")
            time.sleep(0.5)
        pids = {conn.pid for conn in psutil.net_connections(kind='inet') if conn.laddr.port == port and conn.pid}
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    try: child.kill()
                    except: pass
                proc.kill()
                proc.wait(timeout=2)
            except: pass
        return not is_port_in_use(port)
    except: return not is_port_in_use(port)

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def get_active_env_list():
    """Returns a list of names for all services currently ON."""
    health = get_system_health()
    return [name for name, info in health.items() if info['status'] == "ON"]

def report_scenario_result(res_obj):
    """
    Unified reporting for Jarvis test scenarios.
    Handles both live human-readable output and machine JSON.
    """
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    dur = res_obj.get('duration', 0)
    result = res_obj.get('result', "")
    
    # Check if this is a complex/multi-line result (S2S style)
    if res_obj.get('mode') in ["WAV", "STREAM"] and "stt_model" in res_obj:
        if res_obj['mode'] == "STREAM":
            m = res_obj.get('metrics', {})
            t1, t2 = m.get('tts', [0,0])
            main_row = f"  - {status_fmt} {name} (t1:{t1:.2f}s | t2:{t2:.2f}s) | STREAM\n"
            sys.stdout.write(main_row)
            def fmt_range(key):
                r = m.get(key, [0, 0])
                return f"{r[0]:.2f} → {r[1]:.2f}s"
            sys.stdout.write(f"    \t🎙️ {fmt_range('stt')} | [{res_obj.get('stt_model','STT')}] | Text: \"{m.get('stt_text', 'N/A')}\"\n")
            sys.stdout.write(f"    \t🧠 {fmt_range('llm')} | [{res_obj.get('llm_model','LLM')}] | Text: \"{m.get('llm_text', 'N/A').strip()}\"\n")
            sys.stdout.write(f"    \t🔊 {fmt_range('tts')} | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
        else:
            main_row = f"  - {status_fmt} {name} (Total: {dur:.2f}s) | WAV\n"
            sys.stdout.write(main_row)
            sys.stdout.write(f"    \t🎙️ {res_obj.get('stt_inf',0):.2f}s | [{res_obj.get('stt_model','STT')}] | Text: \"{res_obj.get('stt_text','N/A')}\"\n")       
            sys.stdout.write(f"    \t🧠 {res_obj.get('llm_tot',0):.2f}s | [{res_obj.get('llm_model','LLM')}] | Text: \"{res_obj.get('llm_text','N/A')}\"\n")       
            sys.stdout.write(f"    \t🔊 {res_obj.get('tts_inf',0):.2f}s | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
    else:
        # Standard single-line result (STT/TTS style)
        row = f"  - {status_fmt} | {dur:.2f}s | {name:<25} | {result}\n"
        sys.stdout.write(row)

    # Always write machine JSON (silenced in TTY by LiveFilter)
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def run_isolated_lifecycle(name, port, cmd, test_func, cleanup_ports=None):
    """Universal lifecycle manager for isolated tests."""
    ensure_utf8_output()
    if cleanup_ports is None: cleanup_ports = [port]
    
    # 1. Resolve relative paths in cmd if needed
    tests_root = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(tests_root)
    
    print(f"\n--- SMART {name.upper()} LIFECYCLE (Port {port}) ---")
    
    status = get_service_status(port)
    setup_start = time.perf_counter()
    started_here = False
    
    if status == "ON":
        print(f"INFO: Service already healthy. Skipping setup.")
        setup_time = 0
    else:
        if status != "OFF":
            print(f"WARN: Port {port} is {status}. Cleaning up...")
            for p in cleanup_ports: kill_process_on_port(p)
        
        print(f"STARTING {name}...")
        # Use start_server with cwd set to project root
        process = start_server(cmd, loud=False)
        started_here = True
        
        if not wait_for_port(port, timeout=300, process=process):
            print(f"FAILED: {name} failed to start.")
            # Print a hint for debugging
            print(f"DEBUG: Command used: {' '.join(cmd)}")
            return
        setup_time = time.perf_counter() - setup_start

    # 2. Processing
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{name + ' ISOLATED TEST':^120}{RESET}")
    print("="*LINE_LEN)
    
    from contextlib import redirect_stdout
    f = LiveFilter()
    proc_start = time.perf_counter()
    with redirect_stdout(f):
        test_func()
    proc_time = time.perf_counter() - proc_start

    # 3. Cleanup
    cleanup_start = time.perf_counter()
    if started_here:
        print(f"\nCleaning up {name} (Ports: {cleanup_ports})...")
        for p in cleanup_ports: kill_process_on_port(p)
    else:
        print(f"\nINFO: Skipping cleanup (Service was already running).")
    cleanup_time = time.perf_counter() - cleanup_start

    print("="*LINE_LEN)
    time_str = f"Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s"
    print(f"{BOLD}Final Receipt:{RESET} {time_str}")
    print("="*LINE_LEN + "\n")

    receipt = {"setup": setup_time, "processing": proc_time, "cleanup": cleanup_time}
    # Only print machine-readable receipt if output is being captured (not a TTY)
    if not sys.stdout.isatty():
        print(f"LIFECYCLE_RECEIPT: {json.dumps(receipt)}")

def run_s2s_isolated_lifecycle(loadout_name, benchmark_mode=False):
    """S2S specialized lifecycle helper."""
    from s2s.tests import run_test
    cfg = load_config()
    port = cfg['ports']['s2s']
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loadout_path = os.path.join(project_root, "tests", "loadouts", f"{loadout_name}.yaml")
    
    cleanup_ports = [port]
    if os.path.exists(loadout_path):
        with open(loadout_path, "r") as f:
            l_data = yaml.safe_load(f)
            stt_m = l_data.get("stt", [None])[0]
            tts_m = l_data.get("tts", [None])[0]
            if stt_m: cleanup_ports.append(cfg['stt_loadout'][stt_m])
            if tts_m: cleanup_ports.append(cfg['tts_loadout'][tts_m])

    # Use current interpreter
    python_exe = sys.executable
    server_script = os.path.join(project_root, "servers", "s2s_server.py")
    cmd = [python_exe, server_script, "--loadout", loadout_name]
    if benchmark_mode:
        cmd.append("--benchmark-mode")
    
    run_isolated_lifecycle(
        name=f"S2S {loadout_name.upper()}",
        port=port,
        cmd=cmd,
        test_func=lambda: (
            run_test(skip_health=True, loadout_id=loadout_name, stream=False),
            run_test(skip_health=True, loadout_id=loadout_name, stream=True)
        ),
        cleanup_ports=cleanup_ports
    )

def run_stt_isolated_lifecycle(target_id, benchmark_mode=False):
    """STT specialized lifecycle helper."""
    from stt.whisper.tests import run_test
    cfg = load_config()
    port = cfg['stt_loadout'][target_id]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    python_exe = sys.executable
    server_script = os.path.join(project_root, "servers", "stt_server.py")
    cmd = [python_exe, server_script, "--port", str(port), "--model", target_id]
    if benchmark_mode:
        cmd.append("--benchmark-mode")
    
    run_isolated_lifecycle(
        name=f"STT {target_id.upper()}",
        port=port,
        cmd=cmd,
        test_func=lambda: run_test(model_id=target_id)
    )

def run_tts_isolated_lifecycle(target_id, benchmark_mode=False):
    """TTS specialized lifecycle helper."""
    from tts.chatterbox.tests import run_test
    cfg = load_config()
    port = cfg['tts_loadout'][target_id]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    python_exe = sys.executable
    server_script = os.path.join(project_root, "servers", "tts_server.py")
    cmd = [python_exe, server_script, "--port", str(port), "--variant", target_id]
    if benchmark_mode:
        cmd.append("--benchmark-mode")
    
    run_isolated_lifecycle(
        name=f"TTS {target_id.upper()}",
        port=port,
        cmd=cmd,
        test_func=lambda: run_test(variant_id=target_id)
    )