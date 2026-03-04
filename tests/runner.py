import os
import sys
import yaml
import time
import argparse
import threading
import json
import asyncio
from loguru import logger
from contextlib import redirect_stdout

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)
sys.path.insert(1, script_dir)

import utils
from test_utils import (
    CYAN, BOLD, RESET, LINE_LEN, 
    init_session, RichDashboard, AccumulatingReporter,
    save_artifact, trigger_report_generation, run_test_lifecycle
)
from test_utils.mocks import get_mock_implementation
from test_utils.env_simulators import AudioFeeder, ScreenFeeder, KeyboardSandbox
from utils import log_msg
from utils.engine import PipelineResolver, PipelineExecutor

class E2EOrchestrator:
    """Manages virtual environment synchronization for hardware E2E tests."""
    def __init__(self, project_root):
        self.project_root = project_root
        self.audio_feeder = AudioFeeder()
        self.screen_feeder = ScreenFeeder()
        self.kb_sandbox = KeyboardSandbox()

    async def execute_sequence(self, sequence, inputs):
        """Executes a list of virtual environment actions."""
        for step in sequence:
            action = step.get('action')
            if action == 'play_audio':
                path = os.path.join(self.project_root, step['file'])
                self.audio_feeder.play(path)
            elif action == 'set_signal':
                name, val = step['name'], step['value']
                if name == 'ptt_active':
                    sig = inputs.get('ptt_active')
                    if sig:
                        if val: sig.set()
                        else: sig.clear()
            elif action == 'wait':
                await asyncio.sleep(step['ms'] / 1000.0)

class PipelineTestRunner:
    def __init__(self, plan_path, dashboard=None, session_dir=None, reporter=None):
        with open(plan_path, "r") as f:
            self.plan = yaml.safe_load(f)
        self.project_root = project_root
        self.session_dir = session_dir
        # ISOLATION: Point resolver to absolute tests/pipelines/ directory
        base_pipelines_dir = os.path.join(self.project_root, "tests", "pipelines")
        self.resolver = PipelineResolver(self.project_root, base_dir=base_pipelines_dir)
        self.executor = PipelineExecutor(self.project_root, dashboard=dashboard, session_dir=self.session_dir)
        self.integration_scenarios = self.load_scenarios()
        self.dashboard = dashboard
        self.session_dir = session_dir
        self.reporter = reporter
        self.e2e_orchestrator = E2EOrchestrator(self.project_root)

    def load_scenarios(self):
        scenarios = {}
        paths = [
            os.path.join(self.project_root, "tests", "scenarios", "core.yaml"),
            os.path.join(self.project_root, "tests", "scenarios", "e2e_hardware.yaml")
        ]
        for path in paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    scenarios.update(yaml.safe_load(f) or {})
        return scenarios

    def run_scenario(self, sid, pid, mid, domain, l_id, v_ext=0.0, v_static=0.0, overrides=None):
        # 3. Execution (Multi-Input & Multi-Modal Support)
        inputs = {}
        scen_def = self.integration_scenarios.get(sid)
        if not scen_def:
            self.log(f"Scenario '{sid}' not found in core.yaml", level="error")
            return False

        for turn in scen_def.get('turns', []):
            if 'send_binary' in turn:
                inputs['input_mic'] = turn['send_binary']
            
            send_data = turn.get('send', {})
            if isinstance(send_data, dict):
                s_type, content, media = send_data.get('type'), send_data.get('content'), send_data.get('media')
                if s_type == 'context':
                    inputs['input_text'] = content
                    if media: inputs['input_media'] = media
                elif s_type == 'message':
                    if pid == 'atomic_tts': inputs['input_text'] = content
                    elif pid == 'atomic_llm' or pid == 'atomic_vlm': inputs['input_instruction'] = content
                    else: inputs['input_instruction'] = content
                    if media: inputs['input_media'] = media
                elif content: 
                    inputs['input_instruction'] = content
                    if media: inputs['input_media'] = media

        # Synchronized Signal Injection (Always enabled for hardware testing)
        inputs['ptt_active'] = threading.Event()

        start_time = time.perf_counter()
        try:
            # Use the instance resolver (self.resolver) instead of creating a new one
            bound_graph = self.resolver.resolve(pid, mid, overrides=overrides)
            
            async def e2e_wrapper():
                # Launch sequence in background if present
                seq = scen_def.get('sequence')
                if seq:
                    asyncio.create_task(self.e2e_orchestrator.execute_sequence(seq, inputs))
                # Global Scenario Timeout (120s) to prevent hangs
                return await asyncio.wait_for(self.executor.run(bound_graph, inputs), timeout=120.0)

            success = asyncio.run(e2e_wrapper())
        except Exception as e:
            self.log(f"Resolution/Execution Error: {e}", level="error")
            import traceback
            logger.error(traceback.format_exc())
            success = False
            # Create dummy metrics for failed resolution
            node_metrics = {"SYSTEM": {"error": str(e)}}
            res_obj = {
                "name": sid, "status": "FAILED", "duration": 0,
                "pipeline": pid, "domain": domain, "loadout_id": l_id,
                "node_metrics": node_metrics, "vram_peak": 0,
                "result": f"ARCH_MISMATCH: {e}"
            }
            if self.reporter: self.reporter.report(res_obj)
            return False

        duration = time.perf_counter() - start_time
        
        # Save trace artifact for post-hoc analysis
        trace_path = os.path.join(self.session_dir, f"trace_{sid}.json")
        with open(trace_path, "w") as f:
            json.dump(self.executor.trace, f, indent=2)

        # 4. Post-hoc Metric Evaluation (Node-Driven)
        from test_utils.pipeline_evaluator import TraceEvaluator
        evaluator = TraceEvaluator(self.project_root, self.executor.trace)
        
        expected = None
        for turn in scen_def.get('turns', []):
            for exp in turn.get('expect', []):
                if exp.get('type') == 'log' and exp.get('content'): expected = exp['content']

        node_metrics = {}
        for nid, node in bound_graph.items():
            if node['type'] != 'processing': continue
            role = node.get('role', '').lower()
            if role == 'stt': node_metrics[nid] = evaluator.calculate_stt_metrics(nid, expected_text=expected)
            elif role == 'llm': node_metrics[nid] = evaluator.calculate_llm_metrics(nid)
            elif role == 'tts': node_metrics[nid] = evaluator.calculate_tts_metrics(nid)

        status = "PASSED" if success else "FAILED"
        
        # Extraction helpers for reporting
        stt_res = self.executor.results.get("proc_stt", [])
        llm_res = self.executor.results.get("proc_llm", [])
        
        res_obj = {
            "name": sid,
            "status": status,
            "duration": duration,
            "pipeline": pid,
            "domain": domain,
            "loadout_id": l_id,
            "node_metrics": node_metrics,
            "vram_external": v_ext,
            "vram_static": v_static,
            "vram_peak": self.executor.vram_peak,
            "stt_text": "".join(stt_res) if isinstance(stt_res, list) else str(stt_res),
            "llm_text": "".join(llm_res) if isinstance(llm_res, list) else str(llm_res),
            "input_file": inputs.get("input_mic") or inputs.get("input_media", ""),
            "output_file": self.executor.results.get("proc_tts", [""])[0] if isinstance(self.executor.results.get("proc_tts"), list) else self.executor.results.get("proc_tts", "")
        }

        if self.reporter: self.reporter.report(res_obj)
        return success

    def log(self, msg, level="info"):
        fmt_msg = log_msg(msg, tag="runner", level=level)
        if self.dashboard: self.dashboard.log(fmt_msg)

    def run_all(self, args):
        structure = {}
        execution_blocks = self.plan.get('execution', [])
        for block in execution_blocks:
            domain = block.get('domain', 'core').lower()
            pipeline = block.get('pipeline')
            if not pipeline: raise ValueError(f"Block in domain '{domain}' missing explicit 'pipeline' field.")
            
            loadouts = block.get('loadouts', [None])
            scenarios = block.get('scenarios', [])
            if domain not in structure:
                structure[domain] = {"status": "pending", "done": 0, "total": 0, "models_done": 0, "start_time": None, "duration": 0, "loadouts": {}}
            
            structure[domain]['total'] += len(scenarios) * len(loadouts)
            for l in loadouts:
                from utils.config import safe_filename
                l_id = "_".join([safe_filename(m) for m in l]) if isinstance(l, list) else (safe_filename(str(l)) if l else "Live")
                if l_id not in structure[domain]['loadouts']:
                    structure[domain]['loadouts'][l_id] = {"status": "pending", "done": 0, "total": len(scenarios), "duration": 0, "errors": 0, "phase": None, "models": l if isinstance(l, list) else ([str(l)] if l else ["Default"])}

        if self.dashboard:
            self.dashboard.init_plan_structure(structure)
            total_scenarios = sum(d['total'] for d in structure.values())
            total_models = sum(len(d['loadouts']) for d in structure.values())
            self.dashboard.overall_progress.update(self.dashboard.overall_task, total=total_scenarios)
            self.dashboard.overall_progress.update(self.dashboard.models_task, total=total_models)

        for block in execution_blocks:
            domain = block.get('domain', 'core').lower()
            pipeline = block.get('pipeline')
            loadouts = block.get('loadouts', [None])
            scenarios = block.get('scenarios', [])
            mapping = block.get('mapping')
            
            if self.dashboard: self.dashboard.current_domain = domain.upper()

            for l in loadouts:
                from utils.config import safe_filename
                l_id = "_".join([safe_filename(m) for m in l]) if isinstance(l, list) else (safe_filename(str(l)) if l else "Live")
                if self.dashboard: self.dashboard.current_loadout = l_id

                models = l if isinstance(l, list) else ([l] if l else [])
                v_ext = 0.0
                v_static = 0.0

                class ReporterProxy:
                    def __init__(self, target, domain, l_id):
                        self.target, self.domain, self.l_id, self.results = target, domain, l_id, target.results
                    def report(self, res):
                        if isinstance(res, dict): res['domain'], res['loadout_id'] = self.domain, self.l_id
                        self.target.report(res)

                proxy_reporter = ReporterProxy(self.reporter, domain, l_id)

                def on_ready_callback(manager):
                    services = manager.get_registry_entries(domain)
                    try:
                        from manage_loadout import save_runtime_registry
                        save_runtime_registry(services, project_root, external_vram=v_ext)
                    except Exception as e: self.log(f"Failed to update registry: {e}", level="error")

                def execution_wrapper():
                    # At this point v_static has been assigned by run_test_lifecycle
                    
                    # Resolve mapping to implementations if provided
                    overrides = {}
                    
                    # AUTO-MOCK EDGE nodes if requested
                    if args.mock_edge:
                        # Find all source/sink nodes in the current pipeline and mock them
                        try:
                            raw_p = self.resolver.load_yaml(pipeline)
                            for node in raw_p['nodes']:
                                if node['type'] in ['source', 'sink', 'input']:
                                    role = node.get('role', 'unknown')
                                    overrides[node['id']] = get_mock_implementation(f"mock_{node['id']}", role)
                        except: pass

                    # Apply specific mapping from test plan (overwrites auto-mocks)
                    if mapping:
                        for nid, m_def in mapping.items():
                            if isinstance(m_def, str) and m_def.startswith("mock:"):
                                # If it's a specific mock string, extract role from node ID
                                role = "llm" if "llm" in nid else ("stt" if "stt" in nid else "unknown")
                                overrides[nid] = get_mock_implementation(m_def, role, mock_text=m_def.replace("mock:", ""))
                    
                    for s_id in scenarios:
                        self.run_scenario(
                            sid=s_id, pid=pipeline, mid=mapping, domain=domain, l_id=l_id, 
                            v_ext=v_ext, v_static=v_static, 
                            overrides=overrides
                        )

                # Capture pre-load external VRAM
                v_ext = utils.get_gpu_vram_usage()

                setup_time, cleanup_time, prior_vram, model_display, v_ext_actual, v_static_actual = run_test_lifecycle(
                    domain=domain, setup_name=l_id, models=models,
                    purge_on_entry=True if l else False, purge_on_exit=True if l else False,
                    full=True, test_func=execution_wrapper, benchmark_mode=True, session_dir=self.session_dir,
                    on_phase=lambda p: self.dashboard.update_phase(domain, l_id, p) if self.dashboard else None,
                    stub_mode=args.mock_models, reporter=proxy_reporter, on_ready=on_ready_callback
                )
                v_static = v_static_actual
                v_ext = v_ext_actual # Use the internal more accurate external measure

                for r in self.reporter.results:
                    if r.get('loadout_id') == l_id:
                        r['detailed_model'], r['setup_time'], r['cleanup_time'] = model_display, setup_time, cleanup_time
                        if self.dashboard:
                            l_data = self.dashboard.test_data.get(domain, {}).get('loadouts', {}).get(l_id, {})
                            r['log_path'] = l_data.get('log_paths', {}).get('llm') or l_data.get('log_paths', {}).get('sts')

                status = "passed" if structure[domain]['loadouts'][l_id]['errors'] == 0 else "failed"
                if self.dashboard:
                    self.dashboard.finalize_loadout(domain, l_id, setup_time + cleanup_time, status=status)
                    if not args.mock_models: self.dashboard.vram_usage = utils.get_gpu_vram_usage()
                
                loadout_results = [r for r in self.reporter.results if r.get('loadout_id') == l_id]
                save_artifact(domain, [{"loadout": l_id, "scenarios": loadout_results, "status": status.upper()}], session_dir=self.session_dir)
                self.log(f"Finalized loadout: {l_id}")
                print() # SEPARATION

            if self.dashboard: self.dashboard.finalize_domain(domain)

def main():
    parser = argparse.ArgumentParser(description="Jarvis Unified Flow Runner")
    parser.add_argument("plan", type=str)
    
    # New Orthogonal Flags
    parser.add_argument("--mock-models", action="store_true", help="Use zero-VRAM stubs for LLM/STT/TTS.")
    parser.add_argument("--mock-edge", action="store_true", help="Replace hardware drivers (Mic/Speaker) with file-based mocks.")
    
    # Legacy Alias
    parser.add_argument("--mock-all", action="store_true", help="Alias for --mock-models --mock-edge")
    
    args = parser.parse_args()
    
    # Handle Alias
    if args.mock_all:
        args.mock_models = True
        args.mock_edge = True

    plan_path = utils.resolve_path(args.plan)
    with open(plan_path, "r") as f: plan_data = yaml.safe_load(f)

    dashboard = RichDashboard(plan_data.get('name', 'Flow Test'))
    dashboard.start()

    session_dir = "ERROR"
    session_id = "ERROR"
    report_path = None

    try:
        utils.get_hf_home(silent=True)
        utils.get_ollama_models(silent=True)
        session_dir, session_id = init_session(plan_path)
        dashboard.snapshot_path = os.path.join(session_dir, "progression.log")
        
        with open(os.path.join(session_dir, "system_info.yaml"), "r") as f: system_info = yaml.safe_load(f)
        dashboard.finalize_boot(session_id, system_info)
        dashboard.vram_total = utils.get_gpu_total_vram()
        
        log_msg(f"Started session: {session_id}", tag="runner")

        def dashboard_capture(res):
            if not isinstance(res, dict): return
            domain, l_id = res.get('domain'), res.get('loadout_id')
            if domain and l_id: dashboard.update_scenario(domain, l_id, res['name'], res['status'], result=res.get('result', ''))

        reporter = AccumulatingReporter(callback=dashboard_capture)
        runner = PipelineTestRunner(plan_path, dashboard=dashboard, session_dir=session_dir, reporter=reporter)

        def execution_worker():
            nonlocal report_path
            try:
                runner.run_all(args)
                dashboard.current_status = "Generating Report..."
                report_path = trigger_report_generation(upload=True, session_dir=session_dir)
                dashboard.report_url, dashboard.current_status = report_path, "Finished"
                log_msg(f"Report generated: {report_path}", tag="runner")
                time.sleep(1)
            except Exception as e:
                import traceback
                log_msg(f"CRITICAL ERROR: {e}", tag="runner", level="error")
                with open(os.path.join(session_dir, "crash.log"), "w") as f: traceback.print_exc(file=f)

        worker = threading.Thread(target=execution_worker, daemon=True)
        worker.start()
        while worker.is_alive(): time.sleep(0.1)
    finally:
        dashboard.stop()
        print(f"\n✅ Session Complete: {session_id}\n📊 Report: {report_path}")

if __name__ == "__main__":
    main()
