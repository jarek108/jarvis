import sys
import os

# 1. SETUP PATHS FIRST
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)
sys.path.insert(1, script_dir)

# 2. CORE IMPORTS
import argparse
import time
import json
import yaml
import importlib
from contextlib import redirect_stdout

# Import utils packages
import utils
import test_utils

# Import components
from test_utils import (
    CYAN, BOLD, RESET, LINE_LEN, 
    run_test_lifecycle, save_artifact, trigger_report_generation,
    init_session, RichDashboard, AccumulatingReporter
)

def load_scenarios(domain, filter_list=None):
    """Loads scenarios from domain/scenarios.yaml and filters if requested."""
    path = os.path.join(script_dir, domain, "scenarios.yaml")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    # Convert dict to list of named objects
    all_scenarios_map = {k: {"name": k, **v} for k, v in data.items()}
    
    if not filter_list or "all" in filter_list:
        return list(all_scenarios_map.values())
    
    results = []
    for item in filter_list:
        if isinstance(item, str):
            if item in all_scenarios_map:
                results.append(all_scenarios_map[item].copy())
        elif isinstance(item, dict) and "name" in item:
            base_name = item["name"]
            if base_name in all_scenarios_map:
                merged = all_scenarios_map[base_name].copy()
                merged.update(item)
                results.append(merged)
    
    return results

def parse_loadout_entry(entry):
    """Parses a model string like 'model_id#flag1#flag2' into (model_id, flags_dict)."""
    if not isinstance(entry, str): return entry, {}
    parts = entry.split('#')
    model_id = parts[0]
    flags = {}
    for f in parts[1:]:
        if '=' in f:
            k, v = f.split('=', 1)
            flags[k.lower()] = v
        else:
            flags[f.lower()] = True
    return model_id, flags

def run_domain_tests(domain, setup_name, models, scenarios, settings, session_dir, dashboard, plumbing=False, on_scenario=None, on_phase=None):
    """Orchestrates the lifecycle and suite execution for a single domain/setup."""
    # Setup Reporter
    def dashboard_capture(res):
        if on_scenario: on_scenario(res)
    
    reporter = AccumulatingReporter(callback=dashboard_capture)
    
    # Parse Flags from Models
    clean_models = []
    global_flags = {}
    for m in models:
        c_model, flags = parse_loadout_entry(m)
        clean_models.append(c_model)
        global_flags.update(flags)

    # Legacy monkey-patching for non-refactored domains
    import test_utils.reporting
    orig_rep_scen = test_utils.reporting.report_scenario_result
    orig_rep_llm = test_utils.reporting.report_llm_result
    
    def capture_result_legacy(res):
        reporter.report(res)
    
    if domain not in ["stt", "llm"]:
        test_utils.reporting.report_scenario_result = capture_result_legacy
        test_utils.reporting.report_llm_result = capture_result_legacy

    try:
        module_path = f"{domain}.test"
        if module_path in sys.modules: del sys.modules[module_path]
        module = importlib.import_module(module_path)
        
        # Legacy patch for module level
        if domain not in ["stt", "llm"]:
            setattr(module, "report_scenario_result", capture_result_legacy)
            setattr(module, "report_llm_result", capture_result_legacy)
            
        test_func_to_run = getattr(module, "run_test_suite")

        target_id = setup_name
        cfg = utils.load_config()
        for m in clean_models:
            if m.startswith("OL_") or m.startswith("VL_") or m.startswith("vllm:"):
                target_id = m; break
            if domain == "stt" and m in cfg['stt_loadout']: target_id = m; break
            if domain == "tts" and m in cfg['tts_loadout']: target_id = m; break

        def execution_wrapper():
            if domain in ["stt", "llm", "vlm", "sts", "tts"]:
                # Pass flags as kwargs to the test suite
                test_func_to_run(target_id, scenarios_to_run=scenarios, output_dir=session_dir, reporter=reporter, **global_flags)
            else:
                test_func_to_run(target_id, scenarios_to_run=scenarios, output_dir=session_dir)

        setup_time, cleanup_time, prior_vram, model_display = run_test_lifecycle(
            domain=domain, setup_name=setup_name, models=models,
            purge_on_entry=settings.get('purge_on_entry', True),
            purge_on_exit=True, # Force True to ensure isolation between multiple models in one domain
            full=settings.get('full', False),
            test_func=execution_wrapper, 
            benchmark_mode=True,
            force_download=settings.get('force_download', False),
            track_prior_vram=settings.get('track_prior_vram', True),
            session_dir=session_dir,
            on_phase=on_phase,
            stub_mode=plumbing,
            reporter=reporter
        )
    except Exception as e:
        reporter.report({"name": "LIFECYCLE", "status": "FAILED", "result": str(e)})
        setup_time, cleanup_time, prior_vram = 0, 0, 0
        model_display = setup_name
    finally:
        # Restore legacy patching
        if domain not in ["stt", "llm"]:
            test_utils.reporting.report_scenario_result = orig_rep_scen
            test_utils.reporting.report_llm_result = orig_rep_llm

    final_results = [r for r in reporter.results if isinstance(r, dict) and 'name' in r]
    for res in final_results:
        res['setup_time'] = setup_time; res['cleanup_time'] = cleanup_time; res['vram_prior'] = prior_vram
        if res.get('name') in ["LIFECYCLE", "SETUP"]:
            if domain == "stt": res["stt_model"] = model_display
            elif domain == "tts": res["tts_model"] = model_display
            else: res["llm_model"] = model_display
    return final_results, model_display

def main():
    parser = argparse.ArgumentParser(description="Jarvis Plan-Driven Test Runner")
    parser.add_argument("plan", type=str, help="Path to a .yaml test plan (e.g., tests/plan_fast_check.yaml)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip stale artifact cleanup at start")
    parser.add_argument("--plumbing", action="store_true", help="Run in plumbing mode (real servers with stubs)")
    args = parser.parse_args()

    report_path = None
    session_id = "ERROR"
    session_dir = "ERROR"
    vram_summary = {} # domain -> {loadout -> peak_vram}
    
    try:
        # Support both literal paths and '@' prefixed paths
        raw_plan = args.plan[1:] if args.plan.startswith('@') else args.plan
        plan_path = utils.resolve_path(raw_plan)
        
        if not os.path.exists(plan_path):
            print(f"\n❌ ERROR: Plan not found at {plan_path}")
            return
        
        with open(plan_path, "r") as f: plan = yaml.safe_load(f)
        
        # 1. Start Dashboard IMMEDIATELY (Pre-flight transparency)
        dashboard = RichDashboard(plan.get('name', 'Unnamed'))
        dashboard.start()
        
        try:
            # 2. Perform slow pre-flight checks and init session
            dashboard.overall_progress.update(dashboard.boot_task, advance=1, description="Checking HF Cache")
            utils.get_hf_home(silent=True)
            
            dashboard.overall_progress.update(dashboard.boot_task, advance=1, description="Checking Ollama Models")
            utils.get_ollama_models(silent=True)
            
            dashboard.overall_progress.update(dashboard.boot_task, advance=1, description="Initializing Session")
            session_dir, session_id = init_session(plan_path)
            log_file_path = os.path.join(session_dir, "progression.log")
            dashboard.snapshot_path = log_file_path # Triggers background thread in UI
            
            dashboard.overall_progress.update(dashboard.boot_task, advance=1, description="Reading System Info")
            with open(os.path.join(session_dir, "system_info.yaml"), "r") as f: system_info = yaml.safe_load(f)
            
            dashboard.overall_progress.update(dashboard.boot_task, advance=1, description="Finalizing Boot")
            dashboard.finalize_boot(session_id, system_info)
            
            dashboard.vram_total = utils.get_gpu_total_vram()
            
            structure = {}
            execution_blocks = plan.get('execution', [])
            for block in execution_blocks:
                d_name = block['domain'].lower()
                scenarios = load_scenarios(d_name, block.get('scenarios'))
                loadouts = block.get('loadouts', [])
                if d_name not in structure:
                    structure[d_name] = {"status": "pending", "done": 0, "total": 0, "models_done": 0, "start_time": None, "duration": 0, "loadouts": {}}
                structure[d_name]['total'] += len(scenarios) * len(loadouts)
                for models in loadouts:
                    s_name = "_".join([m.replace(":", "-").replace("/", "--") for m in models])
                    structure[d_name]['loadouts'][s_name] = {"status": "pending", "done": 0, "total": len(scenarios), "duration": 0, "errors": 0, "phase": None, "models": models}
            
            dashboard.init_plan_structure(structure)
            
            # Update progress bars with actual totals
            total_scenarios = sum(d['total'] for d in structure.values())
            total_models = sum(len(d['loadouts']) for d in structure.values())
            dashboard.overall_progress.update(dashboard.overall_task, total=total_scenarios)
            dashboard.overall_progress.update(dashboard.models_task, total=total_models)

            def execution_worker():
                try:
                    settings = plan.get('settings', {})
                    for block in execution_blocks:
                        domain = block['domain']; dashboard.current_domain = domain.upper()
                        scenarios = load_scenarios(domain, block.get('scenarios'))
                        loadouts = block.get('loadouts', [])
                        for models in loadouts:
                            s_name = "_".join([m.replace(":", "-").replace("/", "--") for m in models])
                            dashboard.current_loadout = s_name
                            dashboard.update_phase(domain, s_name, "setup", "wip")
                            
                            def dashboard_capture(res):
                                dashboard.update_scenario(domain, s_name, res['name'], res['status'])

                            start_l = time.perf_counter()
                            res, model_display = run_domain_tests(domain, s_name, models, scenarios, settings, session_dir, dashboard, plumbing=args.plumbing, on_scenario=dashboard_capture, on_phase=lambda p: dashboard.update_phase(domain, s_name, p))
                            
                            # Aggregate Peak VRAM
                            if res:
                                peaks = [r.get('vram_peak', 0) for r in res if 'vram_peak' in r]
                                if peaks:
                                    if domain not in vram_summary: vram_summary[domain] = {}
                                    vram_summary[domain][s_name] = max(peaks)
                                
                                # Inject detailed model name and log path for reporting
                                log_paths = dashboard.test_data.get(domain.lower(), {}).get('loadouts', {}).get(s_name, {}).get('log_paths', {})
                                for r in res:
                                    r['detailed_model'] = model_display
                                    # Find relevant log path
                                    m_lower = model_display.lower()
                                    m_type = "llm" if any(x in m_lower for x in ["ol_", "vl_", "vllm:"]) else \
                                             ("stt" if "whisper" in m_lower else \
                                             ("tts" if "chatterbox" in m_lower else "sts"))
                                    r['log_path'] = log_paths.get(m_type) or log_paths.get("sts")

                            status = "failed"; error_message = ""
                            if not res:
                                status = "failed"
                            else:
                                lifecycle_fail = next((r for r in res if r.get('name') in ["SETUP", "LIFECYCLE"] and r.get('status') != "PASSED"), None)
                                if lifecycle_fail:
                                    status = lifecycle_fail['status'].lower()
                                    error_message = lifecycle_fail.get('result', "Lifecycle error")
                                else:
                                    all_passed = all(r.get('status') == "PASSED" for r in res)
                                    status = "passed" if all_passed else "failed"
                            
                            domain_results = [{"loadout": s_name, "scenarios": res or [], "status": status.upper()}]
                            save_artifact(domain, domain_results, session_dir=session_dir)
                            dashboard.finalize_loadout(domain, s_name, time.perf_counter() - start_l, status=status, error_message=error_message)
                            
                            if not args.plumbing:
                                dashboard.vram_usage = utils.get_gpu_vram_usage()
                        dashboard.finalize_domain(domain)
                    dashboard.current_status = "Generating Report..."
                    nonlocal report_path
                    report_path = trigger_report_generation(upload=True, session_dir=session_dir)
                    dashboard.report_url = report_path
                    dashboard.current_status = "Finished"
                    # Small sleep to ensure the Dashboard UI has time to render the final URL
                    time.sleep(1.0)
                except Exception as e:
                    import traceback
                    dashboard.log(f"CRITICAL WORKER ERROR: {str(e)}")
                    with open(os.path.join(session_dir, "worker_crash.log"), "w") as f:
                        traceback.print_exc(file=f)

            import threading
            worker_thread = threading.Thread(target=execution_worker, daemon=True)
            worker_thread.start()

            # Keep main thread alive while worker is running
            while worker_thread.is_alive():
                time.sleep(0.1)
            time.sleep(1) 
        finally:
            dashboard.stop()
            
            if vram_summary:
                print(f"\n{BOLD}{CYAN}󰢮  HARDWARE IMPACT SUMMARY (Peak VRAM usage){RESET}")
                for domain, loadouts in vram_summary.items():
                    print(f"  • {BOLD}{domain.upper()}{RESET}")
                    for loadout, peak in loadouts.items():
                        print(f"    - {loadout:<40} : {BOLD}{peak:.2f} GB{RESET}")

            print(f"\n✅ Session Complete: {session_id}")
            print(f"📁 Artifacts: {session_dir}")
            if report_path: print(f"📊 Report: {report_path}")

    except Exception as e:
        import traceback
        print(f"\n❌ CRITICAL STARTUP ERROR: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
