import os
import sys
import time
import yaml
import json
import subprocess
from contextlib import redirect_stdout
from .config import load_config, resolve_path, get_hf_home, get_ollama_models
from .ui import ensure_utf8_output, LiveFilter, BOLD, CYAN, RESET, LINE_LEN
from .infra import is_port_in_use, start_server, wait_for_port, kill_process_on_port, get_jarvis_ports, kill_all_jarvis_services, is_vllm_model_local
from .vram import get_service_status, get_loaded_ollama_models, get_system_health
from .llm import check_and_pull_model, warmup_llm, is_model_local

class LifecycleManager:
    def __init__(self, setup_name, models=None, purge_on_entry=True, purge_on_exit=False, full=False, benchmark_mode=False, force_download=False, track_prior_vram=True):
        self.setup_name = setup_name
        self.models = models or [] # List of model strings
        self.purge_on_entry = purge_on_entry
        self.purge_on_exit = purge_on_exit
        self.full = full
        self.benchmark_mode = benchmark_mode
        self.force_download = force_download
        self.track_prior_vram = track_prior_vram
        self.cfg = load_config()
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.python_exe = resolve_path(self.cfg['paths']['venv_python'])
        
        # Broadcast standard ENV vars to ensure native libs (whisper, etc) find the right home
        os.environ['HF_HOME'] = get_hf_home()
        os.environ['OLLAMA_MODELS'] = get_ollama_models()
        
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
            elif m.startswith("OL_") or m.startswith("VL_") or m.startswith("vllm:"):
                # Explicit LLM Prefixes
                engine = "ollama"
                model_id = m
                if m.startswith("VL_"):
                    engine = "vllm"
                    model_id = m[3:]
                elif m.startswith("vllm:"):
                    engine = "vllm"
                    model_id = m[5:]
                elif m.startswith("OL_"):
                    engine = "ollama"
                    model_id = m[3:]
                
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
                if self.cfg.get('vllm', {}).get('check_docker', True):
                    from .infra import is_docker_daemon_running
                    if not is_docker_daemon_running():
                        raise RuntimeError("NO-DOCKER")

                vllm_port = self.cfg['ports'].get('vllm', 8300)
                
                # Dynamic VRAM Calculation (GB -> %)
                from .vram import get_gpu_total_vram
                total_vram = get_gpu_total_vram()
                
                # Look up GB requirement
                vram_gb = self.cfg.get('vllm', {}).get('gpu_memory_utilization', 0.5) # Default fallback
                vram_map = self.cfg.get('vllm', {}).get('model_vram_map', {})
                
                # Find best match in map (Sort by length descending so most specific wins)
                match_gb = None
                sorted_keys = sorted(vram_map.keys(), key=len, reverse=True)
                for key in sorted_keys:
                    if key.lower() in model.lower():
                        match_gb = vram_map[key]
                        break
                
                # Check for Calibration History
                model_safe = model.replace("/", "--").replace(":", "-")
                cal_path = os.path.join(self.project_root, "tests", "artifacts", "calibration", f"{model_safe}_trajectory.json")
                if os.path.exists(cal_path):
                    print(f"  ↳ ✅ Integrated: Found calibration history at {os.path.basename(cal_path)}")
                else:
                    print(f"  ↳ ⚠️ Unintegrated: No calibration history found. Using config guestimate.")

                if match_gb:
                    vllm_util = min(0.95, max(0.1, match_gb / total_vram))
                    print(f"  ↳ 🧠 VRAM Mapper: {model} needs {match_gb}GB. Machine has {total_vram:.1f}GB. Setting util to {vllm_util:.3f}")
                else:
                    vllm_util = self.cfg.get('vllm', {}).get('gpu_memory_utilization', 0.5)
                
                # Dynamic Max Model Len lookup
                max_len_map = self.cfg.get('vllm', {}).get('model_max_len_map', {})
                max_len = max_len_map.get('default', 32768)
                for key, val in max_len_map.items():
                    if key.lower() in model.lower():
                        max_len = val
                        break
                
                # Dynamic MM Limit lookup
                mm_limit_map = self.cfg.get('vllm', {}).get('model_mm_limit_map', {})
                mm_limit = mm_limit_map.get('default', '{"image": 1}')
                for key, val in mm_limit_map.items():
                    if key.lower() in model.lower():
                        mm_limit = val
                        break

                hf_cache = get_hf_home()
                cmd = [
                    "docker", "run", "--gpus", "all", "-d", 
                    "--name", "vllm-server", 
                    "-p", f"{vllm_port}:8000", 
                    "-v", f"{hf_cache}:/root/.cache/huggingface", 
                    "vllm/vllm-openai", 
                    model,
                    "--gpu-memory-utilization", str(vllm_util),
                    "--max-model-len", str(max_len),
                    "--limit-mm-per-prompt", mm_limit
                ]
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

    def format_models_for_display(self):
        """Returns a string like 'OL_QWEN-0.5B + WHISPER-TINY'."""
        display_parts = []
        cat = self.identify_models()
        
        if cat['stt']:
            display_parts.append(cat['stt'].upper())
        if cat['llm']:
            prefix = "VL_" if cat['llm']['engine'] == "vllm" else "OL_"
            display_parts.append(f"{prefix}{cat['llm']['model'].upper()}")
        if cat['tts']:
            display_parts.append(cat['tts'].upper())
        
        return " + ".join(display_parts) or self.setup_name.upper()

    def reconcile(self, domain):
        ensure_utf8_output()
        model_str = self.format_models_for_display()
        print(f"\n--- JARVIS LIFECYCLE RECONCILER [Models: {model_str}] ---")
        
        prior_vram = 0.0
        if self.track_prior_vram:
            print("🧹 TRACK PRIOR VRAM: Performing global cleanup for clean baseline...")
            kill_all_jarvis_services()
            from .vram import get_gpu_vram_usage
            prior_vram = get_gpu_vram_usage()
            print(f"  ↳ Baseline External VRAM: {prior_vram:.1f} GB")

        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}

        # 1. Check availability
        if not self.check_availability():
            print(f"❌ MISSING MODELS: {', '.join(self.missing_models)}")
            return -1, prior_vram # Sentinel for missing
        
        if self.purge_on_entry and not self.track_prior_vram:
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
        
        # Setup Persistent Logging Path
        log_dir = os.path.join(self.project_root, "tests", "artifacts", "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        for s in required_services:
            # Special case for Ollama - we handle its startup above for logging (if not already healthy)
            if s['type'] == 'llm' and 'ollama' in str(s['cmd']):
                # But even if it's already healthy, we don't restart it.
                # If we did start it above, it's already in owned_processes.
                if any(p[0] == s['port'] for p in self.owned_processes):
                    continue
                # If it's already ON, we just skip it here
                status, _ = get_service_status(s['port'])
                if status == "ON":
                    print(f"✅ Service LLM [Ollama] already healthy.")
                    continue

            status, info = get_service_status(s['port'])
            if status == "ON": print(f"✅ Service {s['type'].upper()} [{s['id']}] already healthy.")
            else:
                if status != "OFF":
                    print(f"⚠️ Service on port {s['port']} is {status}. Rebirthing...")
                    kill_process_on_port(s['port'])
                
                print(f"🚀 Starting {s['type'].upper()} [{s['id']}]...")
                log_path = os.path.join(log_dir, f"{s['type']}_{s['id'].replace(':', '-').replace('/', '--')}_{timestamp}.log")
                
                # Use a context manager to ensure the file is closed if start_server fails, 
                # but start_server returns immediately, so we need to keep it open or let Popen handle it.
                f_log = open(log_path, "w")
                proc = start_server(s['cmd'], log_file=f_log)
                self.owned_processes.append((s['port'], proc))
                
                # For vLLM (docker -d), the process exits immediately, so don't pass it to wait_for_port
                is_vllm = 'docker' in str(s['cmd'])
                wait_proc = None if is_vllm else proc
                
                # Use global timeout from config
                timeout = self.cfg.get('vllm', {}).get('model_startup_timeout', 600)
                
                if not wait_for_port(s['port'], process=wait_proc, timeout=timeout):
                    if is_vllm:
                        from .infra import get_vllm_logs
                        print("\n--- vLLM DOCKER LOGS ---")
                        print(get_vllm_logs())
                        print("------------------------\n")
                    
                    # Read back some logs on failure
                    try:
                        f_log.flush()
                        with open(log_path, "r") as f_read:
                            lines = f_read.readlines()
                            print(f"\n--- {s['type'].upper()} SERVER LOGS (Last 20 lines) ---")
                            print("".join(lines[-20:]))
                            print("------------------------------------------\n")
                    except: pass
                    
                    raise RuntimeError(f"FAILED to start {s['id']} on port {s['port']} after {timeout}s")
        
        # Warmup LLM
        if domain in ["llm", "vlm", "sts"] or self.full:
            cat = self.identify_models()
            if cat['llm']:
                engine = cat['llm']['engine']
                model = cat['llm']['model']
                if engine == "ollama":
                    check_and_pull_model(model, force_pull=self.force_download)
                
                warmup_llm(model, visual=(domain == "vlm"), engine=engine)
        
        return time.perf_counter() - setup_start, prior_vram

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

def run_test_lifecycle(domain, setup_name, models, purge_on_entry, purge_on_exit, full, test_func, benchmark_mode=False, force_download=False, track_prior_vram=True):
    ensure_utf8_output()
    manager = LifecycleManager(setup_name, models=models, purge_on_entry=purge_on_entry, purge_on_exit=purge_on_exit, full=full, benchmark_mode=benchmark_mode, force_download=force_download, track_prior_vram=track_prior_vram)
    model_display = manager.format_models_for_display()
    
    try:
        setup_time, prior_vram = manager.reconcile(domain)
        if setup_time == -1:
            # Report MISSING
            from .reporting import report_scenario_result
            res_obj = {
                "name": "SETUP", "status": "MISSING", "duration": 0, 
                "result": f"Missing models: {', '.join(manager.missing_models)}", 
                "mode": domain.upper(), "vram_prior": prior_vram,
                "llm_model": model_display, "stt_model": model_display, "tts_model": model_display
            }
            report_scenario_result(res_obj)
            return 0, 0, prior_vram, model_display

        print("\n" + "="*LINE_LEN)
        print(f"{BOLD}{CYAN}{domain.upper() + ' [' + model_display + '] TEST SUITE':^120}{RESET}")
        print("="*LINE_LEN)
        f = LiveFilter(); proc_start = time.perf_counter()
        with redirect_stdout(f): test_func()
        proc_time = time.perf_counter() - proc_start
        cleanup_time = manager.cleanup()
        print("="*LINE_LEN)
        print(f"{BOLD}Final Receipt:{RESET} Setup: {setup_time:.1f}s | Processing: {proc_time:.1f}s | Cleanup: {cleanup_time:.1f}s")
        print("="*LINE_LEN + "\n")
        
        return setup_time, cleanup_time, prior_vram, model_display
    except Exception as e:
        from .reporting import report_scenario_result
        err_msg = str(e)
        status = "FAILED"
        if "NO-DOCKER" in err_msg: status = "NO-DOCKER"
        elif "NO-OLLAMA" in err_msg: status = "NO-OLLAMA"
        
        res_obj = {
            "name": "LIFECYCLE", "status": status, "duration": 0, 
            "result": err_msg, "mode": domain.upper(), "vram_prior": 0.0,
            "llm_model": model_display, "stt_model": model_display, "tts_model": model_display
        }
        report_scenario_result(res_obj)
        print(f"❌ LIFECYCLE ERROR: {e}")
        cleanup_time = manager.cleanup()
        return 0, cleanup_time, 0.0, model_display
