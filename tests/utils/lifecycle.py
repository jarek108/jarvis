import os
import sys
import time
import yaml
import json
from contextlib import redirect_stdout
from .config import load_config
from .ui import ensure_utf8_output, LiveFilter, BOLD, CYAN, RESET, LINE_LEN
from .infra import is_port_in_use, start_server, wait_for_port, kill_process_on_port, get_jarvis_ports, kill_all_jarvis_services
from .vram import get_service_status, get_loaded_ollama_models, get_system_health
from .ollama import check_and_pull_model, warmup_llm

class LifecycleManager:
    def __init__(self, loadout_name, purge=False, full=False, benchmark_mode=False):
        self.loadout_name = loadout_name
        self.purge = purge
        self.full = full
        self.benchmark_mode = benchmark_mode
        self.cfg = load_config()
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.python_exe = sys.executable
        loadout_path = os.path.join(self.project_root, "tests", "loadouts", f"{loadout_name}.yaml")
        if not os.path.exists(loadout_path):
            raise FileNotFoundError(f"Loadout YAML not found: {loadout_path}")
        with open(loadout_path, "r") as f:
            self.loadout = yaml.safe_load(f)
        self.owned_processes = []

    def get_required_services(self, domain=None):
        required = []
        llm_model = self.loadout.get('llm')
        if llm_model and (domain in ["llm", "vlm"] or self.full or domain == "sts"):
            required.append({
                "type": "llm", "id": llm_model, "port": self.cfg['ports']['llm'],
                "cmd": ["ollama", "serve"], "health": f"http://127.0.0.1:{self.cfg['ports']['llm']}/api/tags"
            })
        stt_val = self.loadout.get('stt')
        if stt_val and (domain == "stt" or self.full or domain == "sts"):
            stt_id = stt_val[0] if isinstance(stt_val, list) else stt_val
            stt_port = self.cfg['stt_loadout'][stt_id]
            stt_script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, stt_script, "--port", str(stt_port), "--model", stt_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            required.append({"type": "stt", "id": stt_id, "port": stt_port, "cmd": cmd, "health": f"http://127.0.0.1:{stt_port}/health"})
        tts_val = self.loadout.get('tts')
        if tts_val and (domain == "tts" or self.full or domain == "sts"):
            tts_id = tts_val[0] if isinstance(tts_val, list) else tts_val
            tts_port = self.cfg['tts_loadout'][tts_id]
            tts_script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, tts_script, "--port", str(tts_port), "--variant", tts_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            required.append({"type": "tts", "id": tts_id, "port": tts_port, "cmd": cmd, "health": f"http://127.0.0.1:{tts_port}/health"})
        if domain == "sts":
            sts_port = self.cfg['ports']['sts']
            sts_script = os.path.join(self.project_root, "servers", "sts_server.py")
            cmd = [self.python_exe, sts_script, "--loadout", self.loadout_name]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            required.append({
                "type": "sts", "id": self.loadout_name, "port": sts_port, "cmd": cmd, 
                "health": f"http://127.0.0.1:{sts_port}/health"
            })
        return required

    def reconcile(self, domain):
        ensure_utf8_output()
        print(f"\n--- JARVIS LIFECYCLE RECONCILER [Loadout: {self.loadout_name.upper()}] ---")
        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}
        if self.purge:
            print("🧹 PURGE ENABLED: Cleaning up foreign Jarvis services...")
            for port in get_jarvis_ports():
                if port not in required_ports and is_port_in_use(port):
                    print(f"  ↳ Killing orphaned service on port {port}")
                    kill_process_on_port(port)
            if self.cfg['ports']['llm'] in required_ports:
                loaded = get_loaded_ollama_models()
                target_llm = self.loadout.get('llm')
                if loaded and not any(target_llm in m for m in loaded):
                    print(f"  ↳ ☢️ OLLAMA PURGE: Mismatched models loaded ({loaded}). Restarting Ollama...")
                    start_p = time.perf_counter(); kill_process_on_port(self.cfg['ports']['llm'])
                    print(f"    ✅ Purge complete ({time.perf_counter() - start_p:.2f}s)")
        setup_start = time.perf_counter()
        for s in required_services:
            status, info = get_service_status(s['port'])
            if status == "ON": print(f"✅ Service {s['type'].upper()} [{s['id']}] already healthy.")
            else:
                if status != "OFF":
                    print(f"⚠️ Service on port {s['port']} is {status}. Rebirthing...")
                    kill_process_on_port(s['port'])
                print(f"🚀 Starting {s['type'].upper()} [{s['id']}]...")
                proc = start_server(s['cmd'])
                self.owned_processes.append((s['port'], proc))
                if not wait_for_port(s['port'], process=proc):
                    print(f"❌ FAILED to start {s['id']}"); sys.exit(1)
        if domain in ["llm", "vlm"] or self.full or domain == "sts":
            target_llm = self.loadout.get('llm')
            if target_llm: check_and_pull_model(target_llm); warmup_llm(target_llm, visual=(domain == "vlm"))
        return time.perf_counter() - setup_start

    def cleanup(self):
        if self.purge:
            print("\n🧹 PURGE ENABLED: Performing final global cleanup...")
            start_c = time.perf_counter()
            kill_all_jarvis_services()
            return time.perf_counter() - start_c
            
        if not self.owned_processes:
            print("\nINFO: Skipping cleanup (No services were spawned by this test).")
            return 0
            
        print(f"\nCleaning up {len(self.owned_processes)} spawned services...")
        start_c = time.perf_counter()
        for port, _ in self.owned_processes: kill_process_on_port(port)
        return time.perf_counter() - start_c

def run_test_lifecycle(domain, loadout_name, purge, full, test_func, benchmark_mode=False):
    ensure_utf8_output()
    manager = LifecycleManager(loadout_name, purge=purge, full=full, benchmark_mode=benchmark_mode)
    required = manager.loadout.get(domain)
    if not required and domain == "vlm": required = manager.loadout.get("llm")
    if not required and domain != "sts":
        print(f"❌ ERROR: Loadout '{loadout_name}' does not define a component for domain '{domain}'."); sys.exit(1)
    setup_time = manager.reconcile(domain)
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{domain.upper() + ' [' + loadout_name.upper() + '] TEST SUITE':^120}{RESET}")
    print("="*LINE_LEN)
    f = LiveFilter(); proc_start = time.perf_counter()
    with redirect_stdout(f): test_func()
    proc_time = time.perf_counter() - proc_start
    cleanup_time = manager.cleanup()
    print("="*LINE_LEN)
    print(f"{BOLD}Final Receipt:{RESET} Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s")
    print("="*LINE_LEN + "\n")
