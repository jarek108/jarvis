import os
import sys
import time
import yaml
import json
import subprocess
from contextlib import redirect_stdout
import utils
from utils.console import ensure_utf8_output, BOLD, CYAN, RESET, LINE_LEN
from .ui import LiveFilter

import asyncio

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

    def _parse_flags(self, entry):
        """Parses a model string like 'model_id#flag1#flag2' into a flags_dict."""
        if not isinstance(entry, str): return {}
        parts = entry.split('#')
        flags = {}
        for f in parts[1:]:
            if '=' in f:
                k, v = f.split('=', 1)
                flags[k.lower()] = v
            else:
                flags[f.lower()] = True
        return flags

    def identify_models(self):
        """Categorizes list of strings into STT, TTS, and LLM components, preserving flags."""
        categorized = {"stt": None, "tts": None, "llm": None}
        for m in self.models:
            clean_id = m.split('#')[0]
            flags = self._parse_flags(m)
            
            if clean_id in self.cfg['stt_loadout']:
                categorized['stt'] = {"id": clean_id, "flags": flags}
            elif clean_id in self.cfg['tts_loadout']:
                categorized['tts'] = {"id": clean_id, "flags": flags}
            elif m.startswith("OL_") or m.startswith("VL_") or m.startswith("vllm:"):
                # Explicit LLM Prefixes
                engine = "ollama"
                model_id = clean_id
                if clean_id.startswith("VL_"):
                    engine = "vllm"
                    model_id = clean_id[3:]
                elif clean_id.startswith("vllm:"):
                    engine = "vllm"
                    model_id = clean_id[5:]
                elif clean_id.startswith("OL_"):
                    engine = "ollama"
                    model_id = clean_id[3:]
                
                categorized['llm'] = {"engine": engine, "model": model_id, "original": clean_id, "flags": flags}
        return categorized

    def check_availability(self):
        self.missing_models = []
        if self.cat['llm']:
            engine = self.cat['llm']['engine']
            model = self.cat['llm']['model']
            if engine == "ollama":
                if not utils.is_model_local(model) and not self.force_download:
                    self.missing_models.append(self.cat['llm']['original'])
            elif engine == "vllm":
                if not utils.is_vllm_model_local(model) and not self.force_download:
                    self.missing_models.append(self.cat['llm']['original'])
        
        return len(self.missing_models) == 0

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
                required.append({"type": "llm", "id": f"STUB-{original_id}", "port": llm_port, "cmd": cmd, "health": health})
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
                res_id = f"OL_{model.upper()}"
                if 'stream' in llm_flags or self.kwargs.get('stream'): res_id += "#STREAM"
                res_id += f"#CTX={num_ctx}"
                # ---------------------------------

                required.append({
                    "type": "llm", "id": res_id, "port": self.cfg['ports']['ollama'],
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
                    # SAFETY NET for uncalibrated models
                    max_len = self.cfg.get('vllm', {}).get('uncalibrated_safe_ctx', 8192)
                    safe_vram = self.cfg.get('vllm', {}).get('uncalibrated_safe_vram_gb', 4.0)
                    vllm_util = (safe_vram / total_vram)
                    print(f"\n⚠️  [SmartAllocator] WARNING: No calibration found for {model}.")
                    print(f"⚠️  [SmartAllocator] Falling back to SAFETY NET: {max_len} ctx @ {safe_vram}GB VRAM.\n")

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
                res_id = f"VL_{model.upper()}"
                if self.kwargs.get('nativevideo'): res_id += "#NATIVE"
                if self.kwargs.get('stream'): res_id += "#STREAM"
                res_id += f"#CTX={max_len}"
                if limits.get('image', 1) > 1: res_id += f"#IMG_LIM={limits['image']}"
                if limits.get('video', 1) > 1: res_id += f"#VID_LIM={limits['video']}"
                # ---------------------------------

                hf_cache = utils.get_hf_home(silent=True)
                vlm_input_dir = os.path.join(self.project_root, "tests", "vlm", "input_data")
                
                cmd = [
                    "docker", "run", "--gpus", "all", "--rm",
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
                    "type": "llm", "id": res_id, "port": vllm_port,
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
            required.append({"type": "stt", "id": stt_id, "port": stt_port, "cmd": cmd, "health": f"http://127.0.0.1:{stt_port}/health"})

        # 3. TTS
        if self.cat['tts'] and (domain in ["tts", "sts"] or self.full):
            tts_id = self.cat['tts']['id']
            tts_port = self.cfg['tts_loadout'][tts_id]
            tts_script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, tts_script, "--port", str(tts_port), "--variant", tts_id]
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            if self.stub_mode: cmd.append("--stub")
            required.append({"type": "tts", "id": tts_id, "port": tts_port, "cmd": cmd, "health": f"http://127.0.0.1:{tts_port}/health"})

        # 4. STS
        if domain == "sts":
            sts_port = self.cfg['ports']['sts']
            sts_script = os.path.join(self.project_root, "servers", "sts_server.py")
            cmd = [self.python_exe, sts_script, "--port", str(sts_port), "--trust-deps"]
            if self.cat['stt']: cmd.extend(["--stt", self.cat['stt']['id']])
            if self.cat['tts']: cmd.extend(["--tts", self.cat['tts']['id']])
            if self.cat['llm']: 
                llm_val = self.cat['llm']['original']
                cmd.extend(["--llm", llm_val])
            if self.benchmark_mode: cmd.append("--benchmark-mode")
            if self.stub_mode: cmd.append("--stub")
            
            required.append({
                "type": "sts", "id": self.setup_name, "port": sts_port, "cmd": cmd, 
                "health": f"http://127.0.0.1:{sts_port}/health"
            })
        return required

    def format_models_for_display(self):
        display_parts = []
        if self.cat['stt']: 
            display_parts.append(self.cat['stt']['id'].upper())
        
        if self.cat['llm']:
            llm = self.cat['llm']
            prefix = "VL_" if llm['engine'] == "vllm" else "OL_"
            
            flags = llm.get('flags', {})
            model_id = llm['model'].upper()
            name = f"{prefix}{model_id}"
            
            if flags.get('nativevideo') or self.kwargs.get('nativevideo'):
                name += "#NATIVE"
            
            if flags.get('stream') or self.full: 
                name += "#STREAM"
            
            ctx = flags.get('ctx')
            if not ctx:
                if llm['engine'] == "ollama": ctx = 4096
                else: ctx = self.cfg.get('vllm', {}).get('default_context_size', 16384)
            name += f"#CTX={ctx}"
            
            if llm['engine'] == "vllm":
                img_lim = flags.get('img_lim') or 8
                vid_lim = flags.get('vid_lim')
                if img_lim and int(img_lim) > 1: name += f"#IMG_LIM={img_lim}"
                if vid_lim and int(vid_lim) > 1: name += f"#VID_LIM={vid_lim}"

            display_parts.append(name)
            
        if self.cat['tts']: 
            display_parts.append(self.cat['tts']['id'].upper())
        return " + ".join(display_parts) or self.setup_name.upper()

    def reconcile(self, domain):
        ensure_utf8_output()
        prior_vram = 0.0
        
        # 1. Bulk health check (ONCE)
        health_snapshot = asyncio.run(utils.get_system_health_async())
        
        if self.track_prior_vram:
            if any(svc['status'] != 'OFF' for svc in health_snapshot.values()):
                utils.kill_all_jarvis_services()
                prior_vram = utils.get_gpu_vram_usage()
                health_snapshot = asyncio.run(utils.get_system_health_async())

        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}

        # 2. Optimized Purge & Restart (One pass)
        ports_to_kill = set()
        if self.purge_on_entry and not self.track_prior_vram:
            ports_to_kill.update({port for port, svc in health_snapshot.items() 
                                if port not in required_ports and svc['status'] != 'OFF'})
        
        for s in required_services:
            svc = health_snapshot.get(s['port'], {"status": "OFF", "info": None})
            # If not ON/OFF, it's unhealthy or starting -> Kill it
            if svc['status'] not in ["ON", "OFF"]:
                ports_to_kill.add(s['port'])
            # If we need a STUB but the port is occupied (by ANYTHING) -> Kill it
            elif self.stub_mode and svc['status'] == "ON":
                if s['type'] in ["llm", "vlm"]: 
                    ports_to_kill.add(s['port'])
            # If we are doing a REAL run and the port is occupied -> Kill it
            # (Ensures we don't reuse a port running the WRONG model)
            elif not self.stub_mode and svc['status'] == "ON":
                # Always kill vLLM to ensure fresh model load
                if s['type'] == "llm" and self.cat['llm']['engine'] == "vllm":
                    ports_to_kill.add(s['port'])
                # Always kill STT/TTS servers to ensure they are using the right model/variant
                if s['type'] in ["stt", "tts"]:
                    ports_to_kill.add(s['port'])
        
        if ports_to_kill:
            utils.kill_jarvis_ports(ports_to_kill)
            for p in ports_to_kill: 
                if p in health_snapshot: health_snapshot[p]['status'] = 'OFF'

        setup_start = time.perf_counter()
        
        if not self.stub_mode and not self.check_availability(): return -1, prior_vram

        log_dir = self.session_dir if self.session_dir else os.path.join(self.project_root, "tests", "artifacts", "logs")
        os.makedirs(log_dir, exist_ok=True)

        # 3. Parallel Spawning
        services_to_start = [s for s in required_services if health_snapshot.get(s['port'], {}).get('status') != "ON"]
        for s in services_to_start:
            # Add microsecond-precision or unique enough timestamp to prevent collisions
            spawn_ts = time.strftime("%H%M%S")
            log_path = os.path.join(log_dir, f"svc_{s['type']}_{s['id'].replace(':', '-').replace('/', '--')}_{spawn_ts}.log")
            if self.on_phase: self.on_phase(f"log_path:{s['type']}:{log_path}")
            f_log = open(log_path, "w")
            proc = utils.start_server(s['cmd'], log_file=f_log)
            self.owned_processes.append((s['port'], proc))
            
        # 4. Parallel Wait
        if services_to_start:
            ports_to_wait = [s['port'] for s in services_to_start]
            if self.stub_mode and domain == "sts":
                ports_to_wait = [s['port'] for s in services_to_start if s['type'] == "sts"]
            
            timeout = self.cfg.get('vllm', {}).get('model_startup_timeout', 120)
            if not asyncio.run(utils.wait_for_ports_parallel(ports_to_wait, timeout=timeout, require_stub=self.stub_mode)):
                raise RuntimeError(f"Parallel startup timeout after {timeout}s")
        
        # 5. Warmup (Real mode only)
        if not self.stub_mode and (domain in ["llm", "vlm", "sts"] or self.full):
            if self.cat['llm']:
                engine = self.cat['llm']['engine']; model = self.cat['llm']['model']
                if engine == "ollama": utils.check_and_pull_model(model, force_pull=self.force_download)
                utils.warmup_llm(model, visual=(domain == "vlm"), engine=engine)
        
        return time.perf_counter() - setup_start, prior_vram

    def cleanup(self):
        start_c = time.perf_counter()
        if self.purge_on_exit:
            utils.kill_all_jarvis_services()
            return time.perf_counter() - start_c
            
        if not self.owned_processes: return 0
        
        for port, proc in self.owned_processes:
            if port:
                utils.kill_process_on_port(port)
            
            # Explicitly kill the process object if it's still alive
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except:
                    try: proc.kill()
                    except: pass
        return time.perf_counter() - start_c

def run_test_lifecycle(domain, setup_name, models, purge_on_entry, purge_on_exit, full, test_func, benchmark_mode=False, force_download=False, track_prior_vram=True, session_dir=None, on_phase=None, stub_mode=False, reporter=None, **kwargs):
    ensure_utf8_output()
    manager = LifecycleManager(setup_name, models=models, purge_on_entry=purge_on_entry, purge_on_exit=purge_on_exit, full=full, benchmark_mode=benchmark_mode, force_download=force_download, track_prior_vram=track_prior_vram, session_dir=session_dir, on_phase=on_phase, stub_mode=stub_mode, **kwargs)
    model_display = manager.format_models_for_display()
    f = LiveFilter()
    
    log_dir = session_dir if session_dir else os.path.join(manager.project_root, "tests", "artifacts", "logs")
    os.makedirs(log_dir, exist_ok=True)
    debug_log_path = os.path.join(log_dir, f"lifecycle_{domain}_{setup_name}.log")

    with redirect_stdout(f):
        try:
            if on_phase: on_phase("setup")
            setup_time, prior_vram = manager.reconcile(domain)
            if setup_time == -1:
                err_msg = f"Missing models: {', '.join(manager.missing_models)}"
                res_obj = {"name": "SETUP", "status": "MISSING", "duration": 0, "result": err_msg, "mode": domain.upper(), "vram_prior": prior_vram, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
                if reporter: reporter.report(res_obj)
                else: 
                    from .reporting import report_scenario_result
                    report_scenario_result(res_obj)
                return 0, 0, prior_vram, model_display
            
            if on_phase: on_phase("execution")
            proc_start = time.perf_counter()
            test_func()
            proc_time = time.perf_counter() - proc_start
            
            if on_phase: on_phase("cleanup")
            cleanup_time = manager.cleanup()
            
            # Save successful log too for traceability
            with open(debug_log_path, "w", encoding="utf-8") as lf:
                lf.write(f.getvalue())
                
            return setup_time, cleanup_time, prior_vram, model_display
        except Exception as e:
            err_msg = str(e); status = "FAILED"
            if "NO-DOCKER" in err_msg: status = "NO-DOCKER"
            elif "NO-OLLAMA" in err_msg: status = "NO-OLLAMA"
            res_obj = {"name": "LIFECYCLE", "status": status, "duration": 0, "result": err_msg, "mode": domain.upper(), "vram_prior": 0.0, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
            
            if reporter: reporter.report(res_obj)
            else:
                from .reporting import report_scenario_result
                report_scenario_result(res_obj)
            
            cleanup_time = manager.cleanup()
            
            # CRITICAL: Save the buffer so we can see what went wrong!
            with open(debug_log_path, "w", encoding="utf-8") as lf:
                lf.write(f.getvalue())
                lf.write(f"\nFATAL EXCEPTION: {err_msg}\n")
                import traceback
                traceback.print_exc(file=lf)
                
            return 0, cleanup_time, 0.0, model_display
