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
    def __init__(self, setup_name, models=None, purge_on_entry=True, purge_on_exit=False, full=False, benchmark_mode=False, force_download=False, track_prior_vram=True, session_dir=None, on_phase=None):
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
                from .vram import get_gpu_total_vram
                total_vram = get_gpu_total_vram()
                
                vram_gb = self.cfg.get('vllm', {}).get('gpu_memory_utilization', 0.5) 
                vram_map = self.cfg.get('vllm', {}).get('model_vram_map', {})
                match_gb = None
                sorted_keys = sorted(vram_map.keys(), key=len, reverse=True)
                for key in sorted_keys:
                    if key.lower() in model.lower():
                        match_gb = vram_map[key]; break
                
                if match_gb:
                    vllm_util = min(0.95, max(0.1, match_gb / total_vram))
                else:
                    vllm_util = self.cfg.get('vllm', {}).get('gpu_memory_utilization', 0.5)
                
                max_len_map = self.cfg.get('vllm', {}).get('model_max_len_map', {})
                max_len = max_len_map.get('default', 32768)
                for key, val in max_len_map.items():
                    if key.lower() in model.lower():
                        max_len = val; break
                
                mm_limit_map = self.cfg.get('vllm', {}).get('model_mm_limit_map', {})
                mm_limit = mm_limit_map.get('default', '{"image": 1}')
                for key, val in mm_limit_map.items():
                    if key.lower() in model.lower():
                        mm_limit = val; break

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
        display_parts = []
        cat = self.identify_models()
        if cat['stt']: display_parts.append(cat['stt'].upper())
        if cat['llm']:
            prefix = "VL_" if cat['llm']['engine'] == "vllm" else "OL_"
            display_parts.append(f"{prefix}{cat['llm']['model'].upper()}")
        if cat['tts']: display_parts.append(cat['tts'].upper())
        return " + ".join(display_parts) or self.setup_name.upper()

    def reconcile(self, domain):
        ensure_utf8_output()
        prior_vram = 0.0
        if self.track_prior_vram:
            kill_all_jarvis_services()
            from .vram import get_gpu_vram_usage
            prior_vram = get_gpu_vram_usage()

        required_services = self.get_required_services(domain)
        required_ports = {s['port'] for s in required_services}

        ollama_port = self.cfg['ports']['ollama']
        if ollama_port in required_ports:
            cat = self.identify_models()
            if cat['llm'] and cat['llm']['engine'] == "ollama":
                kill_process_on_port(ollama_port)

        if not self.check_availability(): return -1, prior_vram
        
        if self.purge_on_entry and not self.track_prior_vram:
            for port in get_jarvis_ports():
                if port not in required_ports and is_port_in_use(port):
                    kill_process_on_port(port)

        setup_start = time.perf_counter()
        log_dir = self.session_dir if self.session_dir else os.path.join(self.project_root, "tests", "artifacts", "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        for s in required_services:
            status, _ = get_service_status(s['port'])
            if status != "ON":
                if status != "OFF": kill_process_on_port(s['port'])
                log_path = os.path.join(log_dir, f"svc_{s['type']}_{s['id'].replace(':', '-').replace('/', '--')}_{timestamp}.log")
                if self.on_phase: self.on_phase(f"log_path:{s['type']}:{log_path}")
                f_log = open(log_path, "w")
                proc = start_server(s['cmd'], log_file=f_log)
                self.owned_processes.append((s['port'], proc))
                is_vllm = 'docker' in str(s['cmd'])
                wait_proc = None if is_vllm else proc
                timeout = self.cfg.get('vllm', {}).get('model_startup_timeout', 600)
                if not wait_for_port(s['port'], process=wait_proc, timeout=timeout):
                    if is_vllm:
                        from .infra import get_vllm_logs
                        with open(os.path.join(log_dir, f"docker_vllm_fail_{timestamp}.log"), "w") as f_fail:
                            f_fail.write(get_vllm_logs())
                    raise RuntimeError(f"FAILED to start {s['id']} on port {s['port']} after {timeout}s")
        
        if domain in ["llm", "vlm", "sts"] or self.full:
            cat = self.identify_models()
            if cat['llm']:
                engine = cat['llm']['engine']; model = cat['llm']['model']
                if engine == "ollama": check_and_pull_model(model, force_pull=self.force_download)
                warmup_llm(model, visual=(domain == "vlm"), engine=engine)
        return time.perf_counter() - setup_start, prior_vram

    def cleanup(self):
        if self.purge_on_exit:
            kill_all_jarvis_services(); return 0
        if not self.owned_processes: return 0
        start_c = time.perf_counter()
        for port, _ in self.owned_processes: kill_process_on_port(port)
        return time.perf_counter() - start_c

def run_test_lifecycle(domain, setup_name, models, purge_on_entry, purge_on_exit, full, test_func, benchmark_mode=False, force_download=False, track_prior_vram=True, session_dir=None, on_phase=None):
    ensure_utf8_output()
    manager = LifecycleManager(setup_name, models=models, purge_on_entry=purge_on_entry, purge_on_exit=purge_on_exit, full=full, benchmark_mode=benchmark_mode, force_download=force_download, track_prior_vram=track_prior_vram, session_dir=session_dir, on_phase=on_phase)
    model_display = manager.format_models_for_display()
    try:
        if on_phase: on_phase("setup")
        setup_time, prior_vram = manager.reconcile(domain)
        if setup_time == -1:
            from .reporting import report_scenario_result
            res_obj = {"name": "SETUP", "status": "MISSING", "duration": 0, "result": f"Missing models: {', '.join(manager.missing_models)}", "mode": domain.upper(), "vram_prior": prior_vram, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
            report_scenario_result(res_obj); return 0, 0, prior_vram, model_display
        if on_phase: on_phase("execution")
        f = LiveFilter(); proc_start = time.perf_counter()
        with redirect_stdout(f): test_func()
        proc_time = time.perf_counter() - proc_start
        if on_phase: on_phase("cleanup")
        cleanup_time = manager.cleanup()
        return setup_time, cleanup_time, prior_vram, model_display
    except Exception as e:
        from .reporting import report_scenario_result
        err_msg = str(e); status = "FAILED"
        if "NO-DOCKER" in err_msg: status = "NO-DOCKER"
        elif "NO-OLLAMA" in err_msg: status = "NO-OLLAMA"
        res_obj = {"name": "LIFECYCLE", "status": status, "duration": 0, "result": err_msg, "mode": domain.upper(), "vram_prior": 0.0, "llm_model": model_display, "stt_model": model_display, "tts_model": model_display}
        report_scenario_result(res_obj); cleanup_time = manager.cleanup()
        return 0, cleanup_time, 0.0, model_display
