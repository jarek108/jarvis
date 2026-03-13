import os
import sys
import time
import yaml
import json
import subprocess
import threading
import queue
from contextlib import redirect_stdout
from loguru import logger
import utils
from utils.console import ensure_utf8_output, BOLD, CYAN, RESET, LINE_LEN
from .reporting import LiveFilter

import asyncio

# ... (rest of imports and LifecycleManager)

class UIWorker:
    """Manages a single pre-warmed UI process."""
    _id_counter = 0
    def __init__(self, session_dir, initial_state_file=None, project_root=None):
        self.session_dir = session_dir
        self.initial_state_file = initial_state_file
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.proc = None
        self.orch_log = logger.bind(domain="ORCHESTRATOR")
        self.worker_id = UIWorker._id_counter
        UIWorker._id_counter += 1
        self.ready_file = os.path.join(session_dir, f"worker_{self.worker_id}.ready")
        self.port = None
        self._spawn()

    def _spawn(self):
        if os.path.exists(self.ready_file):
            os.remove(self.ready_file)

        cmd = [sys.executable, os.path.join(self.project_root, "tests", "client", "harness.py"), 
               "--mock-all", "--hold-for-signal", "--ready-file", self.ready_file]
        if self.initial_state_file:
            cmd.extend(["--initial-state", self.initial_state_file])
        
        # On Windows, we must avoid blocking on PIPE. Use a log file for each worker.
        self.log_path = os.path.join(self.session_dir, f"worker_{self.worker_id}.log")
        self.log_file = open(self.log_path, "w")

        env = os.environ.copy()
        if self.session_dir:
            env['JARVIS_SESSION_DIR'] = self.session_dir

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Wait for the "READY_PORT" to appear in the log file
        start_t = time.time()
        while time.time() - start_t < 20:
            if self.proc.poll() is not None:
                raise RuntimeError(f"UI Worker {self.worker_id} died prematurely. Check {self.log_path}")
            
            # Read from log file to find READY_PORT
            if os.path.exists(self.log_path):
                try:
                    with open(self.log_path, "r") as f:
                        content = f.read()
                        if "READY_PORT:" in content:
                            parts = content.split("READY_PORT:")
                            # Take the last occurrence and get the first integer-looking thing after it
                            last_part = parts[-1].split()[0]
                            # Remove any trailing non-digits (like if there was a comma or period)
                            import re
                            match = re.search(r"\d+", last_part)
                            if match:
                                self.port = int(match.group())
                except: pass
            
            if self.port:
                break
            time.sleep(0.5)
        
        if not self.port:
            self.proc.terminate()
            raise RuntimeError(f"UI Worker {self.worker_id} timed out waiting for READY_PORT signal.")
        self.orch_log.debug(f"🟢 UI Worker {self.worker_id} pre-warmed on port {self.port}.")

    def trigger_go(self, config_json=None):
        """Sends the signal to the UI to start its mainloop via TCP socket."""
        if not self.port:
            self.orch_log.error(f"Cannot trigger GO for worker {self.worker_id}: No port assigned.")
            return

        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect(('127.0.0.1', self.port))
                data = config_json if config_json else "{}"
                # Append double newline as EOF marker for the harness
                s.sendall((data + "\n\n").encode('utf-8'))
        except Exception as e:
            self.orch_log.error(f"Failed to trigger GO for worker {self.worker_id} via socket: {e}")

    def terminate(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except: 
                try: self.proc.kill()
                except: pass


class UIWorkerPool:
    """Maintains a pool of pre-warmed UI processes."""
    def __init__(self, session_dir, initial_state_file=None, project_root=None):
        self.session_dir = session_dir
        self.initial_state_file = initial_state_file
        self.project_root = project_root
        self.pool = queue.Queue()
        self._refill_thread = threading.Thread(target=self._refill_loop, daemon=True)
        self._refill_thread.start()

    def _refill_loop(self):
        while True:
            # Check how many workers are currently in the pool + how many are being spawned
            current_count = self.pool.qsize()
            if current_count < 2:
                # Spawn worker in a background thread so we don't block the refill loop
                def spawn_task():
                    try:
                        worker = UIWorker(self.session_dir, initial_state_file=self.initial_state_file, project_root=self.project_root)
                        self.pool.put(worker)
                    except Exception as e:
                        logger.error(f"Failed to pre-warm UI worker: {e}")
                
                threading.Thread(target=spawn_task, daemon=True).start()
                # Give it a tiny bit of breathing room before spawning the next one if needed
                time.sleep(0.1)
            time.sleep(0.5)

    def get_worker(self) -> UIWorker:
        try:
            return self.pool.get(timeout=25.0)
        except queue.Empty:
            raise RuntimeError("Timed out waiting for a pre-warmed UI worker from the pool.")

class LifecycleManager:
    def __init__(self, setup_name, models=None, purge_on_entry=True, purge_on_exit=False, full=False, benchmark_mode=False, force_download=False, track_prior_vram=True, session_dir=None, on_phase=None, stub_mode=False, **kwargs):
        self.setup_name = setup_name
        self.models = models or [] # List of model strings
        self.purge_on_entry = purge_on_entry
        self.purge_on_exit = purge_on_exit
        self.full = full
        self.benchmark_mode = benchmark_mode
        self.force_download = force_download
        self.track_prior_vram = track_prior_vram
        self.session_dir = session_dir
        self.on_phase = on_phase
        self.stub_mode = stub_mode
        self.kwargs = kwargs
        self.cfg = utils.load_config()
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.python_exe = utils.resolve_path(self.cfg['paths']['venv_python'])
        
        # Ensure project root is in sys.path for absolute imports
        if self.project_root not in sys.path:
            sys.path.insert(0, self.project_root)
        
        # Broadcast standard ENV vars
        os.environ['HF_HOME'] = utils.get_hf_home(silent=True)
        os.environ['OLLAMA_MODELS'] = utils.get_ollama_models(silent=True)
        
        self.cat = self.identify_models() # Identified ONCE
        self.display_name = self.format_models_for_display() # Formatted ONCE
        self.owned_processes = []
        self.missing_models = []
        self.uncalibrated_models = []

    def identify_models(self):
        """Categorizes list of strings into STT, TTS, and LLM components using shared parsing logic."""
        categorized = {"stt": None, "tts": None, "llm": None}
        from utils.config import parse_model_string
        
        for m_str in self.models:
            svc = parse_model_string(m_str)
            if not svc: continue
            
            # Map back to LifecycleManager's expected 'cat' format
            stype = "llm"
            if svc['engine'] == "native":
                stype = "stt" if svc['id'] in self.cfg['stt_loadout'] else "tts"
            
            if stype == "llm":
                categorized['llm'] = {
                    "engine": svc['engine'], 
                    "model": svc['id'], 
                    "original": m_str.split('#')[0], 
                    "flags": svc['params']
                }
            else:
                categorized[stype] = {"id": svc['id'], "flags": svc['params']}
        return categorized

    def check_availability(self):
        self.missing_models = []
        self.uncalibrated_models = []
        if self.cat['llm']:
            engine = self.cat['llm']['engine']
            model = self.cat['llm']['model']
            
            # 1. Check Filesystem Presence
            if engine == "ollama":
                if not utils.is_model_local(model) and not self.force_download:
                    self.missing_models.append(self.cat['llm']['original'])
            elif engine == "vllm":
                if not utils.is_vllm_model_local(model) and not self.force_download:
                    self.missing_models.append(self.cat['llm']['original'])
            
            # 2. Check Calibration (Mandatory for vLLM)
            if not self.stub_mode and engine == "vllm":
                base_gb, _ = utils.get_model_calibration(model, engine="vllm")
                if base_gb is None:
                    self.uncalibrated_models.append(self.cat['llm']['original'])
        
        return len(self.missing_models) == 0 and len(self.uncalibrated_models) == 0

    def get_required_services(self, domain=None):
        required = []
        stub_script = os.path.join(self.project_root, "tests", "test_utils", "stubs.py")
        
        # 1. LLM
        if self.cat['llm'] and (domain in ["llm", "vlm", "sts"] or self.full):
            engine = self.cat['llm']['engine']
            model = self.cat['llm']['model']
            original_id = self.cat['llm']['original']
            llm_flags = self.cat['llm'].get('flags', {})
            
            if self.stub_mode:
                llm_port = self.cfg['ports']['ollama'] if engine == "ollama" else self.cfg['ports'].get('vllm', 8300)
                cmd = [self.python_exe, stub_script, "--port", str(llm_port)]
                health = f"http://127.0.0.1:{llm_port}/health"
                required.append({"type": "llm", "id": model, "res_id": f"STUB-{original_id}", "port": llm_port, "cmd": cmd, "health": health})
            elif engine == "ollama":
                # --- START OLLAMA GUARDRAIL ---
                try:
                    # 1. Resolve context length
                    num_ctx = 4096 # Ollama default
                    if 'ctx' in llm_flags:
                        num_ctx = int(llm_flags['ctx'])
                    
                    # 2. Try to load calibration
                    base_gb, cost_10k = utils.get_model_calibration(model, engine="ollama")
                    
                    if base_gb:
                        predicted_gb = base_gb + ((num_ctx / 10000.0) * cost_10k)
                        current_free_gb = utils.get_gpu_total_vram() - utils.get_gpu_vram_usage()
                        
                        if predicted_gb > (current_free_gb * 0.95): # 5% buffer
                            print(f"\n⚠️  [OllamaGuard] WARNING: Model {original_id} requires ~{predicted_gb:.2f}GB VRAM for {num_ctx} ctx.")
                            print(f"⚠️  [OllamaGuard] Only {current_free_gb:.2f}GB is available. CPU OFFLOAD / SLOW PERFORMANCE LIKELY.\n")
                except Exception:
                    pass # Guardrail failure shouldn't block the run
                # --- END OLLAMA GUARDRAIL ---

                # --- RESOLVED ID for Reporting ---
                res_id = f"ollama_{model.upper()}"
                if 'stream' in llm_flags or self.kwargs.get('stream'): res_id += "#STREAM"
                res_id += f"#CTX={num_ctx}"
                # ---------------------------------

                required.append({
                    "type": "llm", "id": model, "res_id": res_id, "port": self.cfg['ports']['ollama'],
                    "cmd": ["ollama", "serve"], "health": f"http://127.0.0.1:{self.cfg['ports']['ollama']}/api/tags"
                })
            elif engine == "vllm":
                if self.cfg.get('vllm', {}).get('check_docker', True):
                    if not utils.is_docker_daemon_running():
                        raise RuntimeError("NO-DOCKER")

                vllm_port = self.cfg['ports'].get('vllm', 8300)
                total_vram = utils.get_gpu_total_vram()
                
                # --- START SMART ALLOCATOR ---
                vllm_util = None
                max_len = None
                
                # 1. Resolve Context Length
                if 'ctx' in llm_flags:
                    max_len = int(llm_flags['ctx'])
                else:
                    max_len = self.cfg.get('vllm', {}).get('default_context_size', 16384)

                # 2. Try to load physical specs for utility calculation
                base_gb, cost_10k = utils.get_model_calibration(model, engine="vllm")
                
                if base_gb:
                    # Formula: Required = Base + (Ctx / 10000 * Cost) + Floor
                    floor_gb = self.cfg.get('vllm', {}).get('vram_static_floor', 1.0)
                    buffer_pct = self.cfg.get('vllm', {}).get('vram_safety_buffer', 0.15)
                    
                    required_gb = base_gb + ((max_len / 10000.0) * cost_10k) + floor_gb
                    vllm_util = (required_gb / total_vram) + buffer_pct
                    print(f"  [SmartAllocator] Physics: {base_gb}GB base + {max_len} ctx + {floor_gb}GB floor. Buffer: {buffer_pct*100}%. Util: {round(vllm_util, 3)}")
                else:
                    raise RuntimeError(f"UNCALIBRATED: Model {model} has no calibration. vLLM requires exact physics to start safely.")

                # 4. Final Clamping
                vllm_util = min(0.95, max(0.1, vllm_util))
                # --- END SMART ALLOCATOR ---
                
                # Multi-modal limits (Flags #img_lim, #vid_lim override config)
                mm_limit_map = self.cfg.get('vllm', {}).get('model_mm_limit_map', {})
                default_limits_str = mm_limit_map.get('default', '{"image": 1, "video": 1}')
                try:
                    limits = json.loads(default_limits_str)
                except:
                    limits = {"image": 1, "video": 1}
                
                if 'img_lim' in llm_flags: limits['image'] = int(llm_flags['img_lim'])
                if 'vid_lim' in llm_flags: limits['video'] = int(llm_flags['vid_lim'])
                mm_limit_json = json.dumps(limits)

                # --- RESOLVED ID for Reporting ---
                res_id = f"vllm_{model}"
                if self.kwargs.get('nativevideo'): res_id += "#NATIVE"
                if self.kwargs.get('stream'): res_id += "#STREAM"
                res_id += f"#CTX={max_len}"
                if limits.get('image', 1) > 1: res_id += f"#IMG_LIM={limits['image']}"
                if limits.get('video', 1) > 1: res_id += f"#VID_LIM={limits['video']}"
                # ---------------------------------

                hf_cache = utils.get_hf_home(silent=True)
                vlm_input_dir = os.path.join(self.project_root, "tests", "data")
                
                cmd = [
                    "docker", "run", "--gpus", "all", "--rm", "-d",
                    "--name", "vllm-server",
                    "-p", f"{vllm_port}:8000", 
                    "-v", f"{hf_cache}:/root/.cache/huggingface", 
                    "-v", f"{vlm_input_dir}:/data",
                    "vllm/vllm-openai", 
                    model,
                    "--gpu-memory-utilization", str(vllm_util),
                    "--max-model-len", str(max_len),
                    "--limit-mm-per-prompt", mm_limit_json,
                    "--allowed-local-media-path", "/data"
                ]
                required.append({
                    "type": "llm", "id": model, "res_id": res_id, "port": vllm_port,
                    "cmd": cmd, "health": f"http://127.0.0.1:{vllm_port}/v1/models"
                })

        # 2. STT
        if self.cat['stt'] and (domain in ["stt", "sts"] or self.full):
            stt_id = self.cat['stt']['id']
            stt_port = self.cfg['stt_loadout'][stt_id]
            stt_script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, stt_script, "--port", str(stt_port), "--model", stt_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            if self.stub_mode: cmd.append("--stub")
            required.append({"type": "stt", "id": stt_id, "res_id": stt_id.upper(), "port": stt_port, "cmd": cmd, "health": f"http://127.0.0.1:{stt_port}/health"})

        # 3. TTS
        if self.cat['tts'] and (domain in ["tts", "sts"] or self.full):
            tts_id = self.cat['tts']['id']
            tts_port = self.cfg['tts_loadout'][tts_id]
            tts_script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, tts_script, "--port", str(tts_port), "--variant", tts_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            if self.stub_mode: cmd.append("--stub")
            required.append({"type": "tts", "id": tts_id, "res_id": tts_id.upper(), "port": tts_port, "cmd": cmd, "health": f"http://127.0.0.1:{tts_port}/health"})

        # 4. STS
        if domain == "sts":
            sts_port = self.cfg['ports']['sts']
            sts_script = os.path.join(self.project_root, "servers", "sts_server.py")
            cmd = [self.python_exe, sts_script, "--port", str(sts_port), "--trust-deps"]
            if self.cat['stt']: cmd.extend(["--stt", self.cat['stt']['id']])
            if self.cat['tts']: cmd.extend(["--tts", self.cat['tts']['id']])
            if self.cat['llm']: 
                cmd.extend(["--llm", self.cat['llm']['model']])
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            if self.stub_mode: cmd.append("--stub")
            
            required.append({
                "type": "sts", "id": self.setup_name, "port": sts_port, "cmd": cmd, 
                "health": f"http://127.0.0.1:{sts_port}/health"
            })
        return required

    def format_models_for_display(self, domain=None):
        required = self.get_required_services(domain)
        # Use res_id if available, otherwise fallback to upper id
        parts = [s.get('res_id', s['id'].upper()) for s in required if s['type'] != 'sts']
        return " + ".join(parts) or self.setup_name.upper()

    def reconcile(self, domain, timeout=None):
        ensure_utf8_output()
        vram_external = utils.get_gpu_vram_usage()
        prior_vram = 0.0
        
        # 1. Bulk health check (ONCE)
        health_snapshot = asyncio.run(utils.get_system_health_async())
        
        if self.track_prior_vram:
            if any(svc['status'] != 'OFF' for svc in health_snapshot.values()):
                utils.kill_all_jarvis_services()
                prior_vram = utils.get_gpu_vram_usage()
                health_snapshot = asyncio.run(utils.get_system_health_async())
            else:
                prior_vram = vram_external

        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}

        # 2. Optimized Purge & Restart (One pass)
        ports_to_kill = set()
        if self.purge_on_entry and not self.track_prior_vram:
            ports_to_kill.update({port for port, svc in health_snapshot.items() 
                                if port not in required_ports and svc['status'] != 'OFF'})
        
        for s in required_services:
            svc = health_snapshot.get(s['port'], {"status": "OFF", "info": None})
            if svc['status'] not in ["ON", "OFF"]:
                ports_to_kill.add(s['port'])
            elif self.stub_mode and svc['status'] == "ON":
                if s['type'] in ["llm", "vlm"]: 
                    ports_to_kill.add(s['port'])
            elif not self.stub_mode and svc['status'] == "ON":
                if s['type'] == "llm" and self.cat['llm']['engine'] == "vllm":
                    ports_to_kill.add(s['port'])
                if s['type'] in ["stt", "tts"]:
                    ports_to_kill.add(s['port'])
        
        if ports_to_kill:
            utils.kill_jarvis_ports(ports_to_kill)
            for p in ports_to_kill: 
                if p in health_snapshot: health_snapshot[p]['status'] = 'OFF'

        setup_start = time.perf_counter()
        if not self.stub_mode and not self.check_availability(): return -1, prior_vram, vram_external, 0.0

        log_dir = self.session_dir if self.session_dir else os.path.join(self.project_root, "tests", "artifacts", "logs")
        os.makedirs(log_dir, exist_ok=True)

        # 3. Parallel Spawning
        services_to_start = [s for s in required_services if health_snapshot.get(s['port'], {}).get('status') != "ON"]
        for s in services_to_start:
            spawn_ts = time.strftime("%H%M%S")
            from utils.config import safe_filename
            safe_sid = safe_filename(s['id'])
            log_path = os.path.join(log_dir, f"svc_{s['type']}_{safe_sid}_{spawn_ts}.log")
            if self.on_phase: self.on_phase(f"log_path:{s['type']}:{log_path}")
            
            f_log = open(log_path, "w")
            # --- ENGINE DIFFERENTIATION ---
            if s['type'] == "llm" and self.cat['llm'] and self.cat['llm']['engine'] == "vllm":
                # For vLLM (Docker), we use a detached run. 
                subprocess.run(s['cmd'], stdout=f_log, stderr=f_log)
                
                # PIPE DOCKER LOGS TO FILE IN BACKGROUND (same as manage_loadout)
                f_log_append = open(log_path, "a")
                tailer = subprocess.Popen(
                    ["docker", "logs", "-f", "vllm-server"], 
                    stdout=f_log_append, stderr=f_log_append, 
                    creationflags=0x08000000 if os.name == 'nt' else 0
                )
                self.owned_processes.append((s['port'], tailer))
            else:
                # Native services (STT/TTS/Ollama) need persistent process handles
                proc = utils.start_server(s['cmd'], log_file=f_log)
                self.owned_processes.append((s['port'], proc))
            
        # 4. Register with Daemon and Wait
        if services_to_start:
            import requests
            watch_payload = {
                "loadout_id": self.setup_name,
                "external_vram": vram_external,
                "models": self.get_registry_entries(domain)
            }
            try:
                requests.post("http://127.0.0.1:5555/watch", json=watch_payload, timeout=2.0)
            except Exception as e:
                logger.warning(f"Failed to register models with Daemon: {e}")
            
            # USE CONFIG TIMEOUT BUT CAP AT GLOBAL TIMEOUT
            startup_timeout = self.cfg.get('vllm', {}).get('model_startup_timeout', 120)
            if timeout and timeout < startup_timeout:
                startup_timeout = timeout

            # Poll the daemon for global readiness
            poll_start = time.perf_counter()
            ready = False
            while (time.perf_counter() - poll_start) < startup_timeout:
                try:
                    r = requests.get("http://127.0.0.1:5555/status", timeout=1.0).json()
                    if r.get('global_state') == 'READY':
                        ready = True
                        break
                    elif r.get('global_state') == 'ERROR':
                        raise RuntimeError("Daemon reported ERROR state during model startup.")
                except Exception as e:
                    # Fallback if daemon is down
                    if not asyncio.run(utils.wait_for_ports_parallel([s['port'] for s in services_to_start], timeout=1.0, require_stub=self.stub_mode)):
                        pass
                    else:
                        ready = True
                        break
                time.sleep(1.0)
            
            if not ready:
                raise RuntimeError(f"Parallel startup timeout after {startup_timeout}s")
        
        # 5. Warmup
        if not self.stub_mode and (domain in ["llm", "vlm", "sts"] or self.full):
            if self.cat['llm']:
                engine = self.cat['llm']['engine']; model = self.cat['llm']['model']
                if engine == "ollama": utils.check_and_pull_model(model, force_pull=self.force_download)
                utils.warmup_llm(model, visual=(domain == "vlm"), engine=engine)
        
        vram_static = utils.get_gpu_vram_usage()
        return time.perf_counter() - setup_start, prior_vram, vram_external, vram_static

    def cleanup(self):
        start_c = time.perf_counter()
        if self.purge_on_exit:
            utils.kill_all_jarvis_services()
            return time.perf_counter() - start_c
            
        if not self.owned_processes: return 0
        
        for port, proc in self.owned_processes:
            if port:
                utils.kill_process_on_port(port)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except:
                    try: proc.kill()
                    except: pass
        return time.perf_counter() - start_c

    def get_registry_entries(self, domain=None):
        required = self.get_required_services(domain)
        entries = []
        for s in required:
            if s['type'] == 'sts': continue
            
            engine = s['type']
            if engine == "llm":
                engine = self.cat['llm']['engine'] if self.cat['llm'] else "ollama"
            elif engine in ["stt", "tts"]:
                engine = "native"
            
            entries.append({
                "id": s['id'], # Canonical ID for capability matching
                "engine": engine, 
                "port": s['port'],
                "params": self.cat.get(s['type'], {}).get('flags', {}) if s['type'] in self.cat and self.cat[s['type']] else {}
            })
        return entries

def run_test_lifecycle(domain, setup_name, models, purge_on_entry, purge_on_exit, full, test_func, benchmark_mode=False, force_download=False, track_prior_vram=True, session_dir=None, on_phase=None, stub_mode=False, reporter=None, on_ready=None, global_timeout=None, **kwargs):
    ensure_utf8_output()
    manager = LifecycleManager(setup_name, models=models, purge_on_entry=purge_on_entry, purge_on_exit=purge_on_exit, full=full, benchmark_mode=benchmark_mode, force_download=force_download, track_prior_vram=track_prior_vram, session_dir=session_dir, on_phase=on_phase, stub_mode=stub_mode, **kwargs)
    model_display = manager.format_models_for_display(domain=domain)
    f = LiveFilter()
    
    log_dir = session_dir if session_dir else os.path.join(manager.project_root, "tests", "artifacts", "logs")
    os.makedirs(log_dir, exist_ok=True)
    debug_log_path = os.path.join(log_dir, f"lifecycle_{domain}_{setup_name}.log")

    start_time = time.perf_counter()

    with redirect_stdout(f):
        try:
            if on_phase: on_phase("setup")
            # Enforce timeout on setup phase
            setup_time, prior_vram, vram_external, vram_static = manager.reconcile(domain, timeout=global_timeout)
            
            if on_ready: 
                try: on_ready(manager)
                except: pass

            if setup_time == -1:
                # ... skipping SETUP error handling logic (unchanged) ...
                if manager.uncalibrated_models:
                    err_msg = f"Skipped: Missing calibration for vLLM models: {', '.join(manager.uncalibrated_models)}. Run 'python tools/calibrate_models.py' first."
                    status = "UNCALIBRATED"
                else:
                    err_msg = f"Missing model files: {', '.join(manager.missing_models)}"
                    status = "MISSING"
                
                res_obj = {"name": "SETUP", "status": status, "duration": 0, "result": err_msg, "mode": domain.upper(), "vram_prior": prior_vram, "vram_external": vram_external, "vram_static": vram_static, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
                if reporter: reporter.report(res_obj)
                else: 
                    from .reporting import report_scenario_result
                    report_scenario_result(res_obj)
                return 0, 0, prior_vram, model_display, vram_external, vram_static
            
            # Check if we have time left for execution
            if global_timeout:
                elapsed = time.perf_counter() - start_time
                if elapsed >= global_timeout:
                    raise TimeoutError(f"Global scenario timeout ({global_timeout}s) exceeded during setup phase.")

            if on_phase: on_phase("execution")
            test_func()
            
            if on_phase: on_phase("cleanup")
            cleanup_time = manager.cleanup()
            
            with open(debug_log_path, "w", encoding="utf-8") as lf:
                lf.write(f.getvalue())
                
            return setup_time, cleanup_time, prior_vram, model_display, vram_external, vram_static
        except Exception as e:
            err_msg = str(e); status = "FAILED"
            if "NO-DOCKER" in err_msg: status = "NO-DOCKER"
            elif "NO-OLLAMA" in err_msg: status = "NO-OLLAMA"
            res_obj = {"name": "LIFECYCLE", "status": status, "duration": 0, "result": err_msg, "mode": domain.upper(), "vram_prior": 0.0, "vram_external": 0.0, "vram_static": 0.0, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
            
            if reporter: reporter.report(res_obj)
            else:
                from .reporting import report_scenario_result
                report_scenario_result(res_obj)
            
            cleanup_time = manager.cleanup()
            with open(debug_log_path, "w", encoding="utf-8") as lf:
                lf.write(f.getvalue())
                lf.write(f"\nFATAL EXCEPTION: {err_msg}\n")
                import traceback
                traceback.print_exc(file=lf)
                
            return 0, cleanup_time, 0.0, model_display, 0.0, 0.0

