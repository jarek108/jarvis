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
                
                if is_vllm:
                    time.sleep(1) # Moment for container creation
                    log_streamer = subprocess.Popen(
                        ["docker", "logs", "-f", "vllm-server"],
                        stdout=f_log, stderr=f_log,
                        creationflags=0x08000000 if os.name == 'nt' else 0
                    )
                    self.owned_processes.append((None, log_streamer))

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
