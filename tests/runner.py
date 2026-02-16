import argparse
import sys
import os
import time
import json
import yaml
import importlib
from contextlib import redirect_stdout
import utils as j_utils

# Add project root and tests root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(script_dir)
sys.path.append(project_root)

from utils import (
    CYAN, BOLD, RESET, LINE_LEN, 
    run_test_lifecycle, save_artifact, trigger_report_generation,
    resolve_path, init_session, RichDashboard,
    get_gpu_total_vram, get_gpu_vram_usage
)

def load_scenarios(domain, filter_list=None):
    """Loads scenarios from domain/scenarios.yaml and filters if requested."""
    path = os.path.join(script_dir, domain, "scenarios.yaml")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    # Convert dict to list of named objects
    all_scenarios = [{"name": k, **v} for k, v in data.items()]
    
    if not filter_list or "all" in filter_list:
        return all_scenarios
    
    return [s for s in all_scenarios if s['name'] in filter_list]

def run_domain_tests(domain, setup_name, models, scenarios, settings, session_dir, dashboard, mock=False, on_scenario=None, on_phase=None):
    """Orchestrates the lifecycle and suite execution for a single domain/setup."""
    if mock:
        import random
        cfg = j_utils.load_config().get('mock', {})
        s_range = cfg.get('setup_range', [1.0, 3.0])
        e_range = cfg.get('execution_range', [0.2, 1.0])
        c_range = cfg.get('cleanup_range', [0.5, 2.0])
        
        results_accumulator = []
        model_display = " + ".join([m.upper() for m in models]) or setup_name.upper()
        
        if on_phase: on_phase("setup")
        for m in models:
            m_lower = m.lower()
            m_type = "llm" if any(x in m_lower for x in ["ol_", "vl_", "vllm:"]) else \
                     ("stt" if "whisper" in m_lower else \
                     ("tts" if "chatterbox" in m_lower else "sts"))
            if on_phase: on_phase(f"log_path:{m_type}:{session_dir}")

        setup_time = random.uniform(*s_range); time.sleep(setup_time)
        fail_chance = cfg.get('failure_chance', 0.1)
        
        if on_phase: on_phase("execution")
        for s in scenarios:
            exec_time = random.uniform(*e_range); time.sleep(exec_time)
            status = "PASSED" if random.random() > fail_chance else "FAILED"
            res = {"name": s['name'], "status": status, "duration": exec_time, "setup_time": setup_time, "cleanup_time": random.uniform(*c_range), "vram_prior": random.uniform(1.0, 4.0), "vram_peak": random.uniform(4.0, 12.0), "result": f"MOCK RESULT: {random.randint(100, 999)}", "input_file": f"mock_input_{s['name']}.wav", "mode": "MOCK"}
            if domain == "stt": res.update({"match_pct": random.uniform(0.7, 1.0), "output_text": "Mock STT result."})
            elif domain == "tts": res.update({"output_file": os.path.join(session_dir, f"mock_{setup_name}_{s['name']}.wav"), "input_text": "Mock TTS."})
            elif domain == "llm": res.update({"ttft": 0.2, "tps": 40, "text": "Mock LLM."})
            elif domain == "sts": res.update({"stt_text": "Mock", "llm_text": "Mock", "output_file": os.path.join(session_dir, f"mock_sts_{s['name']}.wav"), "metrics": {"stt": [0, 0.2], "llm": [0.2, 0.5], "tts": [0.5, 1.0]}})
            results_accumulator.append(res)
            if on_scenario: on_scenario(res)
        
        if on_phase: on_phase("cleanup")
        cln_time = random.uniform(*c_range); time.sleep(cln_time)
        d_data = dashboard.test_data.get(domain.lower())
        if d_data:
            l_data = d_data['loadouts'].get(setup_name)
            if l_data: l_data['timers'] = {"stp": setup_time, "exec": sum(r['duration'] for r in results_accumulator), "cln": cln_time}
        return results_accumulator

    # --- REAL RUN PATH ---
    results_accumulator = []
    import utils
    import utils.reporting
    
    orig_rep_scen = utils.reporting.report_scenario_result
    orig_rep_llm = utils.reporting.report_llm_result
    orig_rep_scen_u = getattr(utils, 'report_scenario_result', None)
    orig_rep_llm_u = getattr(utils, 'report_llm_result', None)

    def capture_result(res):
        results_accumulator.append(res)
        orig_rep_scen(res)
        if on_scenario: on_scenario(res)
            
    def capture_llm_result(res):
        results_accumulator.append(res)
        orig_rep_llm(res)
        if on_scenario: on_scenario(res)

    utils.reporting.report_scenario_result = capture_result
    utils.reporting.report_llm_result = capture_llm_result
    utils.report_scenario_result = capture_result
    utils.report_llm_result = capture_llm_result

    try:
        module_path = f"{domain}.test"
        if module_path in sys.modules: del sys.modules[module_path]
        module = importlib.import_module(module_path)
        setattr(module, "report_scenario_result", capture_result)
        setattr(module, "report_llm_result", capture_llm_result)
        test_func_to_run = getattr(module, "run_test_suite")

        target_id = setup_name
        for m in models:
            if m.startswith("OL_") or m.startswith("VL_") or m.startswith("vllm:"):
                target_id = m; break
            if domain == "stt" and m in j_utils.load_config()['stt_loadout']: target_id = m; break
            if domain == "tts" and m in j_utils.load_config()['tts_loadout']: target_id = m; break

        setup_time, cleanup_time, prior_vram, model_display = run_test_lifecycle(
            domain=domain, setup_name=setup_name, models=models,
            purge_on_entry=settings.get('purge_on_entry', True),
            purge_on_exit=settings.get('purge_on_exit', True),
            full=settings.get('full', False),
            test_func=lambda: test_func_to_run(target_id, scenarios_to_run=scenarios, output_dir=session_dir), 
            benchmark_mode=True,
            force_download=settings.get('force_download', False),
            track_prior_vram=settings.get('track_prior_vram', True),
            session_dir=session_dir,
            on_phase=on_phase
        )
    except Exception as e:
        results_accumulator.append({"name": "LIFECYCLE", "status": "FAILED", "result": str(e)})
        setup_time, cleanup_time, prior_vram = 0, 0, 0
        model_display = setup_name
    finally:
        utils.reporting.report_scenario_result = orig_rep_scen
        utils.reporting.report_llm_result = orig_rep_llm
        if orig_rep_scen_u: utils.report_scenario_result = orig_rep_scen_u
        if orig_rep_llm_u: utils.report_llm_result = orig_rep_llm_u

    final_results = [r for r in results_accumulator if isinstance(r, dict) and 'name' in r]
    for res in final_results:
        res['setup_time'] = setup_time; res['cleanup_time'] = cleanup_time; res['vram_prior'] = prior_vram
        if res.get('name') in ["LIFECYCLE", "SETUP"]:
            if domain == "stt": res["stt_model"] = model_display
            elif domain == "tts": res["tts_model"] = model_display
            else: res["llm_model"] = model_display
    return final_results

def main():
    parser = argparse.ArgumentParser(description="Jarvis Plan-Driven Test Runner")
    parser.add_argument("plan", type=str, help="Path to a .yaml test plan (e.g., tests/plan_fast_check.yaml)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip stale artifact cleanup at start")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode (no models, simulated data)")
    args = parser.parse_args()

    report_path = None
    plan_path = resolve_path(args.plan)
    if not os.path.exists(plan_path):
        print(f"âŒ ERROR: Plan not found at {plan_path}"); return
    
    session_dir, session_id = init_session(plan_path)
    if args.mock:
        with open(os.path.join(session_dir, "MOCK_RUN"), "w") as f: f.write("True")

    with open(plan_path, "r") as f: plan = yaml.safe_load(f)
    with open(os.path.join(session_dir, "system_info.yaml"), "r") as f: system_info = yaml.safe_load(f)

    dashboard = RichDashboard(plan.get('name', 'Unnamed'), session_id, system_info)
    dashboard.vram_total = get_gpu_total_vram()
    
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
    log_file_path = os.path.join(session_dir, "progression.log")
    dashboard.start(snapshot_path=log_file_path)

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
                res = run_domain_tests(domain, s_name, models, scenarios, settings, session_dir, dashboard, mock=args.mock, on_scenario=dashboard_capture, on_phase=lambda p: dashboard.update_phase(domain, s_name, p))
                
                status = "FAILED"; error_message = ""
                if not res:
                    status = "FAILED"
                else:
                    lifecycle_fail = next((r for r in res if r.get('name') in ["SETUP", "LIFECYCLE"] and r.get('status') != "PASSED"), None)
                    if lifecycle_fail:
                        status = lifecycle_fail['status']
                        error_message = lifecycle_fail.get('result', "Lifecycle error")
                    else:
                        all_passed = all(r.get('status') == "PASSED" for r in res)
                        status = "PASSED" if all_passed else "FAILED"
                
                domain_results = [{"loadout": s_name, "scenarios": res or [], "status": status}]
                save_artifact(domain, domain_results, session_dir=session_dir)
                dashboard.finalize_loadout(domain, s_name, time.perf_counter() - start_l, status=status, error_message=error_message)
                
                if args.mock:
                    import random; dashboard.vram_usage = random.uniform(2.0, 24.0)
                else:
                    dashboard.vram_usage = get_gpu_vram_usage()
            dashboard.finalize_domain(domain)

        dashboard.current_status = "Generating Report..."
        report_path = trigger_report_generation(upload=True, session_dir=session_dir)
        dashboard.report_url = report_path
        dashboard.current_status = "Finished"
        time.sleep(1) 
    finally:
        dashboard.stop()
        print(f"\nâœ… Session Complete: {session_id}")
        print(f"ðŸ“‚ Artifacts: {session_dir}")
        if report_path: print(f"ðŸ“Š Report: {report_path}")

if __name__ == "__main__":
    main()
