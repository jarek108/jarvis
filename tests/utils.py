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
        self.out = sys.stdout

    def write(self, s):
        for line in s.splitlines(keepends=True):
            is_machine = line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ") or line.startswith("VRAM_AUDIT_RESULT: ")
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
    if not is_port_in_use(port): return "OFF", None
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == 11434: url = f"http://127.0.0.1:{port}/api/tags"
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            if port == 11434:
                return "ON", "Ollama Core"
            return ("BUSY" if data.get("status") == "busy" else "ON"), data.get("model") or data.get("variant") or "Ready"
        elif response.status_code == 503 and response.json().get("status") == "STARTUP":
            return "STARTUP", "Loading..."
        return "UNHEALTHY", None
    except:
        return "UNHEALTHY", None

def get_system_health():
    """Returns a full map of all known ports defined in config.yaml."""
    cfg = load_config()
    health = {}
    
    # 1. System Core
    s2s_status, s2s_info = get_service_status(cfg['ports']['s2s'])
    health[cfg['ports']['s2s']] = {"status": s2s_status, "info": s2s_info, "label": "S2S", "type": "s2s"}
    
    llm_status, llm_info = get_service_status(cfg['ports']['llm'])
    health[cfg['ports']['llm']] = {"status": llm_status, "info": llm_info, "label": "LLM", "type": "llm"}
    
    # 2. All defined STT ports
    for name, port in cfg['stt_loadout'].items():
        status, info = get_service_status(port)
        health[port] = {"status": status, "info": info, "label": name, "type": "stt"}
        
    # 3. All defined TTS ports
    for name, port in cfg['tts_loadout'].items():
        status, info = get_service_status(port)
        health[port] = {"status": status, "info": info, "label": name, "type": "tts"}
        
    return health

def start_server(cmd, loud=False):
    flags = subprocess.CREATE_NEW_CONSOLE if loud else (0x08000000 if os.name == 'nt' else 0)
    final_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd]) if isinstance(cmd, list) else cmd
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.Popen(final_cmd, creationflags=flags, shell=True, cwd=project_root)

def wait_for_port(port: int, timeout: int = 60, process=None) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        status, info = get_service_status(port)
        if status == "ON": return True
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

def get_jarvis_ports():
    """Returns a set of all ports defined in config.yaml for Jarvis services."""
    cfg = load_config()
    ports = {cfg['ports']['s2s'], cfg['ports']['llm']}
    ports.update(cfg['stt_loadout'].values())
    ports.update(cfg['tts_loadout'].values())
    return ports

def get_loaded_ollama_models():
    """Returns a list of models currently loaded in Ollama VRAM."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp.status_code == 200:
            return [m['name'] for m in resp.json().get('models', [])]
    except:
        pass
    return []

class LifecycleManager:
    def __init__(self, loadout_name, purge=False, full=False, benchmark_mode=False):
        self.loadout_name = loadout_name
        self.purge = purge
        self.full = full
        self.benchmark_mode = benchmark_mode
        self.cfg = load_config()
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.python_exe = sys.executable
        
        # Load the YAML
        loadout_path = os.path.join(self.project_root, "tests", "loadouts", f"{loadout_name}.yaml")
        if not os.path.exists(loadout_path):
            raise FileNotFoundError(f"Loadout YAML not found: {loadout_path}")
        
        with open(loadout_path, "r") as f:
            self.loadout = yaml.safe_load(f)
        
        self.owned_processes = []

    def get_required_services(self, domain=None):
        """
        Determines which services are required based on the domain and 'full' flag.
        Returns a list of (name, port, cmd, health_url)
        """
        required = []
        
        # 1. LLM
        llm_model = self.loadout.get('llm')
        if llm_model and (domain == "llm" or self.full or domain == "s2s"):
            required.append({
                "type": "llm",
                "id": llm_model,
                "port": self.cfg['ports']['llm'],
                "cmd": ["ollama", "serve"],
                "health": f"http://127.0.0.1:{self.cfg['ports']['llm']}/api/tags"
            })

        # 2. STT
        stt_list = self.loadout.get('stt', [])
        if stt_list and (domain == "stt" or self.full or domain == "s2s"):
            stt_id = stt_list[0]
            stt_port = self.cfg['stt_loadout'][stt_id]
            stt_script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, stt_script, "--port", str(stt_port), "--model", stt_id]
            if self.benchmark_mode:
                cmd.append("--benchmark-mode")
            required.append({
                "type": "stt",
                "id": stt_id,
                "port": stt_port,
                "cmd": cmd,
                "health": f"http://127.0.0.1:{stt_port}/health"
            })

        # 3. TTS
        tts_list = self.loadout.get('tts', [])
        if tts_list and (domain == "tts" or self.full or domain == "s2s"):
            tts_id = tts_list[0]
            tts_port = self.cfg['tts_loadout'][tts_id]
            tts_script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, tts_script, "--port", str(tts_port), "--variant", tts_id]
            if self.benchmark_mode:
                cmd.append("--benchmark-mode")
            required.append({
                "type": "tts",
                "id": tts_id,
                "port": tts_port,
                "cmd": cmd,
                "health": f"http://127.0.0.1:{tts_port}/health"
            })

        # 4. S2S (Always if domain is s2s)
        if domain == "s2s":
            s2s_port = self.cfg['ports']['s2s']
            s2s_script = os.path.join(self.project_root, "servers", "s2s_server.py")
            cmd = [self.python_exe, s2s_script, "--loadout", self.loadout_name]
            if self.benchmark_mode:
                cmd.append("--benchmark-mode")
            required.append({
                "type": "s2s",
                "id": self.loadout_name,
                "port": s2s_port,
                "cmd": cmd,
                "health": f"http://127.0.0.1:{s2s_port}/health"
            })

        return required

    def reconcile(self, domain):
        """The core logic to ensure, purge, and warmup the environment."""
        ensure_utf8_output()
        print(f"\n--- JARVIS LIFECYCLE RECONCILER [Loadout: {self.loadout_name.upper()}] ---")
        
        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}
        jarvis_ports = get_jarvis_ports()
        
        # 1. PURGE
        if self.purge:
            print(f"🧹 PURGE ENABLED: Cleaning up foreign Jarvis services...")
            for port in jarvis_ports:
                if port not in required_ports and is_port_in_use(port):
                    print(f"  ↳ Killing orphaned service on port {port}")
                    kill_process_on_port(port)
            
            # Nuclear Ollama check
            if self.cfg['ports']['llm'] in required_ports:
                loaded = get_loaded_ollama_models()
                target_llm = self.loadout.get('llm')
                if loaded and not any(target_llm in m for m in loaded):
                    print(f"  ↳ ☢️ OLLAMA PURGE: Mismatched models loaded ({loaded}). Restarting Ollama...")
                    start_purge = time.perf_counter()
                    kill_process_on_port(self.cfg['ports']['llm'])
                    print(f"    ✅ Purge complete ({time.perf_counter() - start_purge:.2f}s)")

        # 2. ENSURE
        setup_start = time.perf_counter()
        for s in required_services:
            status = get_service_status(s['port'])
            if status == "ON":
                print(f"✅ Service {s['type'].upper()} [{s['id']}] already healthy.")
            else:
                if status != "OFF":
                    print(f"⚠️ Service on port {s['port']} is {status}. Rebirthing...")
                    kill_process_on_port(s['port'])
                
                print(f"🚀 Starting {s['type'].upper()} [{s['id']}]...")
                proc = start_server(s['cmd'])
                self.owned_processes.append((s['port'], proc))
                if not wait_for_port(s['port'], process=proc):
                    print(f"❌ FAILED to start {s['id']}")
                    sys.exit(1)

        # 3. WARMUP (Special handling for LLM)
        if domain == "llm" or self.full or domain == "s2s":
            target_llm = self.loadout.get('llm')
            if target_llm:
                check_and_pull_model(target_llm)
                warmup_llm(target_llm)

        return time.perf_counter() - setup_start

    def cleanup(self):
        if not self.owned_processes:
            print(f"\nINFO: Skipping cleanup (No services were spawned by this test).")
            return 0
        
        print(f"\nCleaning up {len(self.owned_processes)} spawned services...")
        start_cleanup = time.perf_counter()
        for port, _ in self.owned_processes:
            kill_process_on_port(port)
        return time.perf_counter() - start_cleanup

def run_test_lifecycle(domain, loadout_name, purge, full, test_func, benchmark_mode=False):
    """Unified wrapper to be used by all test.py scripts."""
    ensure_utf8_output()
    manager = LifecycleManager(loadout_name, purge=purge, full=full, benchmark_mode=benchmark_mode)
    
    # Validation
    required = manager.loadout.get(domain)
    if not required and domain != "s2s": # S2S always has a loadout name
        print(f"❌ ERROR: Loadout '{loadout_name}' does not define a component for domain '{domain}'.")
        sys.exit(1)

    setup_time = manager.reconcile(domain)

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{domain.upper() + ' [' + loadout_name.upper() + '] TEST SUITE':^120}{RESET}")
    print("="*LINE_LEN)
    
    from contextlib import redirect_stdout
    f = LiveFilter()
    proc_start = time.perf_counter()
    with redirect_stdout(f):
        test_func()
    proc_time = time.perf_counter() - proc_start

    cleanup_time = manager.cleanup()

    print("="*LINE_LEN)
    time_str = f"Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s"
    print(f"{BOLD}Final Receipt:{RESET} {time_str}")
    print("="*LINE_LEN + "\n")

# --- KEEPING EXISTING REPORTING AND HELPER FUNCTIONS ---

def check_and_pull_model(model_name):
    """Ensures an Ollama model is available."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags")
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            if any(model_name in m for m in models): return True
        
        print(f"Model {model_name} not found. Pulling (this may take a while)...")
        subprocess.run(["ollama", "pull", model_name], check=True)
        return True
    except:
        return False

def warmup_llm(model_name):
    """Performs a dummy request to hot-load the model into VRAM."""
    print(f"🔥 Warming up {model_name} (Hot-loading weights)...")
    try:
        requests.post("http://127.0.0.1:11434/api/chat", json={
            "model": model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False
        }, timeout=120)
    except Exception as e:
        print(f"⚠️ Warmup failed: {e}")

def get_gpu_vram_usage():
    """Returns current VRAM usage in GB via nvidia-smi."""
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"]
        output = subprocess.check_output(cmd, text=True).strip()
        return float(output) / 1024.0
    except:
        return 0.0

def check_ollama_offload(model_name):
    """Checks if an Ollama model is fully in VRAM."""
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            for m in models:
                if model_name in m['name']:
                    size = m.get('size', 0)
                    vram = m.get('size_vram', 0)
                    return (vram >= size), vram / (1024**3), size / (1024**3)
        return True, 0.0, 0.0
    except:
        return True, 0.0, 0.0

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def fmt_with_chunks(text, chunks):
    """Adds (timestamp) markers to text based on chunk data."""
    if not chunks: return text
    out = []
    for c in chunks:
        out.append(f"{c['text']} ({c['end']:.2f} → {c['end']:.2f}s)")
    return " ".join(out)

def report_llm_result(res_obj):
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    tps = res_obj.get('tps', 0)
    text = res_obj.get('text', "N/A")
    thought = res_obj.get('thought', "")
    t1 = res_obj.get('ttft', 0)
    t2 = res_obj.get('duration', 0)
    if res_obj.get('chunks'):
        text = fmt_with_chunks(res_obj.get('raw_text', ""), res_obj.get('chunks'))
    row = f"  - {status_fmt} | {t1:.3f} → {t2:.3f}s | TPS:{tps:.1f} | Scenario: {name:<15}\n"
    sys.stdout.write(row)
    if thought:
        sys.stdout.write(f"    \t💭 Thought: \"{thought[:100]}...\"\n")
    sys.stdout.write(f"    \t🧠 Text: \"{text}\"\n")
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    dur = res_obj.get('duration', 0)
    result = res_obj.get('result', "")
    if res_obj.get('mode') in ["WAV", "STREAM"] and "stt_model" in res_obj:
        m = res_obj.get('metrics', {})
        if res_obj['mode'] == "STREAM":
            t1_audio, t2_audio = m.get('tts', [0,0])
            sys.stdout.write(f"  - {status_fmt} {name} ({t1_audio:.2f} → {t2_audio:.2f}s) | STREAM\n")
            def fmt_range(key):
                r = m.get(key, [0, 0])
                return f"{r[0]:.2f} → {r[1]:.2f}s"
            stt_ready = m.get('stt',[0,0])[1]
            stt_text = f"{m.get('stt_text', 'N/A')} ({stt_ready:.2f} → {stt_ready:.2f}s)"
            llm_text = fmt_with_chunks(m.get('llm_text', 'N/A').strip(), m.get('llm_chunks', []))
            if "(" not in llm_text and llm_text != "N/A":
                llm_end = m.get('llm',[0,0])[1]
                llm_text = f"{llm_text} ({llm_end:.2f} → {llm_end:.2f}s)"
            sys.stdout.write(f"    \t🎙️ {fmt_range('stt')} | [{res_obj.get('stt_model','STT')}] | Text: \"{stt_text}\"\n")
            sys.stdout.write(f"    \t🧠 {fmt_range('llm')} | [{res_obj.get('llm_model','LLM')}] | Text: \"{llm_text}\"\n")
            sys.stdout.write(f"    \t🔊 {fmt_range('tts')} | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
        else:
            stt_end = res_obj.get('stt_inf', 0)
            llm_end = stt_end + res_obj.get('llm_tot', 0)
            sys.stdout.write(f"  - {status_fmt} {name} ({dur:.2f} → {dur:.2f}s) | WAV\n")
            fmt_stt = f"{stt_end:.2f} → {stt_end:.2f}s"
            fmt_llm = f"{llm_end:.2f} → {llm_end:.2f}s"
            fmt_tts = f"{dur:.2f} → {dur:.2f}s"
            sys.stdout.write(f"    \t🎙️ {fmt_stt} | [{res_obj.get('stt_model','STT')}] | Text: \"{res_obj.get('stt_text','N/A')} ({fmt_stt})\"\n")
            sys.stdout.write(f"    \t🧠 {fmt_llm} | [{res_obj.get('llm_model','LLM')}] | Text: \"{res_obj.get('llm_text','N/A')} ({fmt_llm})\"\n")
            sys.stdout.write(f"    \t🔊 {fmt_tts} | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
    else:
        sys.stdout.write(f"  - {status_fmt} | {dur:.2f}s | {name:<25} | {result}\n")
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def list_all_loadouts():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loadout_dir = os.path.join(project_root, "tests", "loadouts")
    if not os.path.exists(loadout_dir): return []
    return [f.replace(".yaml", "") for f in os.listdir(loadout_dir) if f.endswith(".yaml")]

def list_all_llm_models():
    loadouts = list_all_loadouts()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models = set()
    for lid in loadouts:
        path = os.path.join(project_root, "tests", "loadouts", f"{lid}.yaml")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                if data.get('llm'): models.add(data['llm'])
        except: pass
    return sorted(list(models))

def list_all_stt_models():
    cfg = load_config()
    return sorted(list(cfg.get('stt_loadout', {}).keys()))

def list_all_tts_models():
    cfg = load_config()
    return sorted(list(cfg.get('tts_loadout', {}).keys()))
