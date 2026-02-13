import os
import sys
import time
import yaml
import json
from contextlib import redirect_stdout
from .config import load_config
from .ui import ensure_utf8_output, LiveFilter, BOLD, CYAN, RESET, LINE_LEN
from .infra import is_port_in_use, start_server, wait_for_port, kill_process_on_port, get_jarvis_ports, kill_all_jarvis_services, is_vllm_model_local
from .vram import get_service_status, get_loaded_ollama_models, get_system_health
from .ollama import check_and_pull_model, warmup_llm, is_model_local

class LifecycleManager:
    def __init__(self, setup_name, models=None, purge_on_entry=True, purge_on_exit=False, full=False, benchmark_mode=False, force_download=False):
        self.setup_name = setup_name
        self.models = models or [] # List of model strings
        self.purge_on_entry = purge_on_entry
        self.purge_on_exit = purge_on_exit
        self.full = full
        self.benchmark_mode = benchmark_mode
        self.force_download = force_download
        self.cfg = load_config()
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.python_exe = sys.executable
        self.owned_processes = []
        self.missing_models = []

    def identify_models(self):
        """Categorizes list of strings into STT, TTS, and LLM components."""
        categorized = {"stt": None, "tts": None, "llm": None}
        for m in self.models:
            if m in self.cfg['stt_loadout']:
                categorized['stt'] = m
            elif m in self.cfg['tts_loadout']:
                categorized['tts'] = m
            else:
                # Assume LLM
                engine = "ollama"
                model_id = m
                if m.startswith("vllm:"):
                    engine = "vllm"
                    model_id = m[5:]
                elif ":" in m or "/" in m: # Heuristic for org/model or model:tag
                    engine = "ollama" # default
                
                categorized['llm'] = {"engine": engine, "model": model_id, "original": m}
        return categorized

    def check_availability(self):
        cat = self.identify_models()
        self.missing_models = []
        
        if cat['llm']:
            engine = cat['llm']['engine']
            model = cat['llm']['model']
            if engine == "ollama":
                if not is_model_local(model) and not self.force_download:
                    self.missing_models.append(cat['llm']['original'])
            elif engine == "vllm":
                if not is_vllm_model_local(model) and not self.force_download:
                    self.missing_models.append(cat['llm']['original'])
        
        # Note: STT and TTS models are currently local scripts/files
        # and don't require external downloads in the same way LLMs do.
        return len(self.missing_models) == 0

    def get_required_services(self, domain=None):
        required = []
        cat = self.identify_models()
        
        # 1. LLM
        if cat['llm'] and (domain in ["llm", "vlm", "sts"] or self.full):
            engine = cat['llm']['engine']
            model = cat['llm']['model']
            original_id = cat['llm']['original']
            if engine == "ollama":
                required.append({
                    "type": "llm", "id": original_id, "port": self.cfg['ports']['ollama'],
                    "cmd": ["ollama", "serve"], "health": f"http://127.0.0.1:{self.cfg['ports']['ollama']}/api/tags"
                })
            elif engine == "vllm":
                vllm_port = self.cfg['ports'].get('vllm', 8300)
                hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
                cmd = ["docker", "run", "--gpus", "all", "-d", "--name", "vllm-server", "-p", f"{vllm_port}:8000", "-v", f"{hf_cache}:/root/.cache/huggingface", "vllm/vllm-openai", "--model", model]
                required.append({
                    "type": "llm", "id": original_id, "port": vllm_port,
                    "cmd": cmd, "health": f"http://127.0.0.1:{vllm_port}/v1/models"
                })

        # 2. STT
        if cat['stt'] and (domain in ["stt", "sts"] or self.full):
            stt_id = cat['stt']
            stt_port = self.cfg['stt_loadout'][stt_id]
            stt_script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, stt_script, "--port", str(stt_port), "--model", stt_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            required.append({"type": "stt", "id": stt_id, "port": stt_port, "cmd": cmd, "health": f"http://127.0.0.1:{stt_port}/health"})

        # 3. TTS
        if cat['tts'] and (domain in ["tts", "sts"] or self.full):
            tts_id = cat['tts']
            tts_port = self.cfg['tts_loadout'][tts_id]
            tts_script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, tts_script, "--port", str(tts_port), "--variant", tts_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            required.append({"type": "tts", "id": tts_id, "port": tts_port, "cmd": cmd, "health": f"http://127.0.0.1:{tts_port}/health"})

        # 4. STS
        if domain == "sts":
            sts_port = self.cfg['ports']['sts']
            sts_script = os.path.join(self.project_root, "servers", "sts_server.py")
            # PASS EXPLICIT OVERRIDES to sts_server
            cmd = [self.python_exe, sts_script, "--port", str(sts_port)]
            if cat['stt']: cmd.extend(["--stt", cat['stt']])
            if cat['tts']: cmd.extend(["--tts", cat['tts']])
            if cat['llm']: 
                llm_val = cat['llm']['original']
                cmd.extend(["--llm", llm_val])
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            
            required.append({
                "type": "sts", "id": self.setup_name, "port": sts_port, "cmd": cmd, 
                "health": f"http://127.0.0.1:{sts_port}/health"
            })
        return required

    def reconcile(self, domain):
        ensure_utf8_output()
        print(f"\n--- JARVIS LIFECYCLE RECONCILER [Setup: {self.setup_name.upper()}] ---")
        
        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}

        # 1. Start LLM Engine FIRST if it's Ollama, so we can check availability
        ollama_port = self.cfg['ports']['ollama']
        if ollama_port in required_ports:
            cat = self.identify_models()
            if cat['llm'] and cat['llm']['engine'] == "ollama":
                status, _ = get_service_status(ollama_port)
                if status != "ON":
                    print(f"🚀 Starting Ollama (required for availability check)...")
                    # Find the ollama service config
                    ollama_service = next(s for s in required_services if s['port'] == ollama_port)
                    proc = start_server(ollama_service['cmd'])
                    self.owned_processes.append((ollama_port, proc))
                    if not wait_for_port(ollama_port, process=proc):
                        print(f"❌ FAILED to start Ollama")
                        return -1

        # 2. Now check availability
        if not self.check_availability():
            print(f"❌ MISSING MODELS: {', '.join(self.missing_models)}")
            return -1 # Sentinel for missing
        
        if self.purge_on_entry:
            print("🧹 PURGE ON ENTRY: Cleaning up foreign Jarvis services...")
            for port in get_jarvis_ports():
                if port not in required_ports and is_port_in_use(port):
                    print(f"  ↳ Killing orphaned service on port {port}")
                    kill_process_on_port(port)
            
            # Special check for Ollama model mismatch
            ollama_port = self.cfg['ports']['ollama']
            if ollama_port in required_ports:
                cat = self.identify_models()
                if cat['llm'] and cat['llm']['engine'] == "ollama":
                    target_llm = cat['llm']['model']
                    loaded = get_loaded_ollama_models()
                    if loaded and not any(target_llm in m for m in loaded):
                        print(f"  ↳ ☢️ OLLAMA PURGE: Mismatched models loaded ({loaded}). Restarting Ollama...")
                        kill_process_on_port(ollama_port)

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
                
                # For vLLM (docker -d), the process exits immediately, so don't pass it to wait_for_port
                is_vllm = 'docker' in str(s['cmd'])
                wait_proc = None if is_vllm else proc
                
                timeout = 300 if is_vllm else 120
                if not wait_for_port(s['port'], process=wait_proc, timeout=timeout):
                    raise RuntimeError(f"FAILED to start {s['id']} on port {s['port']}")
        
        # Warmup LLM
        if domain in ["llm", "vlm", "sts"] or self.full:
            cat = self.identify_models()
            if cat['llm']:
                engine = cat['llm']['engine']
                model = cat['llm']['model']
                if engine == "ollama":
                    check_and_pull_model(model, force_pull=self.force_download)
                    warmup_llm(model, visual=(domain == "vlm"))
        
        return time.perf_counter() - setup_start

    def cleanup(self):
        if self.purge_on_exit:
            print("\n🧹 PURGE ON EXIT: Performing final global cleanup...")
            start_c = time.perf_counter()
            kill_all_jarvis_services()
            return time.perf_counter() - start_c
            
        if not self.owned_processes:
            return 0
            
        print(f"\nCleaning up {len(self.owned_processes)} spawned services...")
        start_c = time.perf_counter()
        for port, _ in self.owned_processes: kill_process_on_port(port)
        return time.perf_counter() - start_c

def run_test_lifecycle(domain, setup_name, models, purge_on_entry, purge_on_exit, full, test_func, benchmark_mode=False, force_download=False):
    ensure_utf8_output()
    manager = LifecycleManager(setup_name, models=models, purge_on_entry=purge_on_entry, purge_on_exit=purge_on_exit, full=full, benchmark_mode=benchmark_mode, force_download=force_download)
    
    setup_time = manager.reconcile(domain)
    if setup_time == -1:
        # Report MISSING
        from .reporting import report_scenario_result
        res_obj = {"name": "SETUP", "status": "MISSING", "duration": 0, "result": f"Missing models: {', '.join(manager.missing_models)}", "mode": domain.upper()}
        report_scenario_result(res_obj)
        return 0, 0 # Return 0s for missing

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{CYAN}{domain.upper() + ' [' + setup_name.upper() + '] TEST SUITE':^120}{RESET}")
    print("="*LINE_LEN)
    f = LiveFilter(); proc_start = time.perf_counter()
    with redirect_stdout(f): test_func()
    proc_time = time.perf_counter() - proc_start
    cleanup_time = manager.cleanup()
    print("="*LINE_LEN)
    print(f"{BOLD}Final Receipt:{RESET} Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s")
    print("="*LINE_LEN + "\n")
    
    return setup_time, cleanup_time
