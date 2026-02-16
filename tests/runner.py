import argparse
import sys
import os
import time
import json
import yaml
import importlib
from contextlib import redirect_stdout
import utils

# Add project root and tests root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(script_dir)
sys.path.append(project_root)

from utils import (
    CYAN, BOLD, RESET, LINE_LEN, 
    run_test_lifecycle, save_artifact, trigger_report_generation,
    resolve_path, init_session, RichDashboard, ProgressionLogger,
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

def run_domain_tests(domain, setup_name, models, scenarios, settings, session_dir, progression_logger, dashboard, mock=False, on_scenario=None, on_phase=None):
    """Orchestrates the lifecycle and suite execution for a single domain/setup."""
    if mock:
        import random
        cfg = utils.load_config().get('mock', {})
        s_range = cfg.get('setup_range', [1.0, 3.0])
        e_range = cfg.get('execution_range', [0.2, 1.0])
        c_range = cfg.get('cleanup_range', [0.5, 2.0])
        
        results_accumulator = []
        model_display = " + ".join([m.upper() for m in models]) or setup_name.upper()
        
        if progression_logger: progression_logger.log(f"[MOCK] Simulating {domain.upper()} with {model_display}")
        if on_phase: on_phase("setup")
        
        # Signal mock logs for each model
        for m in models:
            m_lower = m.lower()
            m_type = "llm" if any(x in m_lower for x in ["ol_", "vl_", "vllm:"]) else \
                     ("stt" if "whisper" in m_lower else \
                     ("tts" if "chatterbox" in m_lower else "sts"))
            if on_phase: on_phase(f"log_path:{m_type}:{session_dir}")

        setup_time = random.uniform(*s_range)
        time.sleep(setup_time) # Simulate setup
        
        # Inject timers into dashboard structure via on_phase or manually
        # Since on_phase is a lambda p: dashboard.update_phase(...), we can't easily pass the time back
        # Let's assume the dashboard handles live timing, and we just finalize at the end.
        
        fail_chance = cfg.get('failure_chance', 0.1)
        
        if on_phase: on_phase("execution")
        for s in scenarios:
            exec_time = random.uniform(*e_range)
            time.sleep(exec_time) # Simulate execution
            status = "PASSED" if random.random() > fail_chance else "FAILED"
            
            res = {
                "name": s['name'],
                "status": status,
                "duration": exec_time,
                "setup_time": setup_time,
                "cleanup_time": random.uniform(*c_range),
                "vram_prior": random.uniform(1.0, 4.0),
                "vram_peak": random.uniform(4.0, 12.0),
                "result": f"MOCK RESULT: {random.randint(100, 999)}",
                "input_file": f"mock_input_{s['name']}.wav",
                "mode": "MOCK"
            }
            # ... (rest of mock updates)
            if domain == "stt":
                res.update({"match_pct": random.uniform(0.7, 1.0), "output_text": "The quick brown fox jumps over the lazy dog."})
            elif domain == "tts":
                out_path = os.path.join(session_dir, f"mock_{setup_name}_{s['name']}.wav")
                with open(out_path, "wb") as f: f.write(b"MOCK AUDIO DATA")
                res.update({"output_file": out_path, "input_text": "Sample TTS input."})
            elif domain == "llm":
                res.update({"ttft": random.uniform(0.1, 0.5), "tps": random.uniform(20, 60), "text": "This is a mock LLM response."})
            elif domain == "sts":
                out_path = os.path.join(session_dir, f"mock_sts_{s['name']}.wav")
                with open(out_path, "wb") as f: f.write(b"MOCK STS AUDIO")
                res.update({
                    "stt_text": "Mock STT input", "llm_text": "Mock LLM response",
                    "output_file": out_path,
                    "metrics": {
                        "stt": [0, random.uniform(0.1, 0.5)],
                        "llm": [random.uniform(0.2, 0.4), random.uniform(1.0, 2.0)],
                        "tts": [random.uniform(1.1, 1.5), random.uniform(2.0, 3.0)]
                    }
                })

            results_accumulator.append(res)
            if on_scenario: on_scenario(res)
            if progression_logger:
                icon = "✅" if status == "PASSED" else "❌"
                progression_logger.log(f"[MOCK] {icon} Scenario: {s['name']}")
        
        if on_phase: on_phase("cleanup")
        cleanup_time = random.uniform(*c_range)
        time.sleep(cleanup_time)
        
        # Inject final timers
        d_data = dashboard.test_data.get(domain.lower())
        if d_data:
            l_data = d_data['loadouts'].get(setup_name)
            if l_data:
                l_data['timers'] = {"stp": setup_time, "exec": sum(r['duration'] for r in results_accumulator), "cln": cleanup_time}

        return results_accumulator

    try:
        module_path = f"{domain}.test"
        module = importlib.import_module(module_path)
        test_func_to_run = getattr(module, "run_test_suite")
    except (ImportError, AttributeError) as e:
        if progression_logger: progression_logger.log(f"Could not load test suite for domain '{domain}': {e}", level="ERROR")
        return None

    results_accumulator = []
    
    # Wrap domain's reporter to capture results locally
    original_report_scenario = getattr(importlib.import_module("utils"), "report_scenario_result")
    original_report_llm = getattr(importlib.import_module("utils"), "report_llm_result")
    
    def capture_result(res):
        results_accumulator.append(res)
        original_report_scenario(res)
        if on_scenario: on_scenario(res)
        if progression_logger:
            status_icon = "✅" if res['status'] == "PASSED" else "❌"
            progression_logger.log(f"{status_icon} Scenario: {res['name']} ({res['status']})")
            
    def capture_llm_result(res):
        results_accumulator.append(res)
        original_report_llm(res)
        if on_scenario: on_scenario(res)
        if progression_logger:
            status_icon = "✅" if res['status'] == "PASSED" else "❌"
            progression_logger.log(f"{status_icon} Scenario: {res['name']} ({res['status']})")

    setattr(module, "report_scenario_result", capture_result)
    setattr(module, "report_llm_result", capture_llm_result)

    # Resolve target ID for domain (what is passed to test_func)
    target_id = setup_name
    for m in models:
        # LLM takes priority for ID if it has a prefix
        if m.startswith("OL_") or m.startswith("VL_") or m.startswith("vllm:"):
            target_id = m
            break
        if domain == "stt" and m in utils.load_config()['stt_loadout']: target_id = m; break
        if domain == "tts" and m in utils.load_config()['tts_loadout']: target_id = m; break

    try:
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
            progression_logger=progression_logger,
            on_phase=on_phase
        )
    except Exception as e:
        if progression_logger: progression_logger.log(f"UNEXPECTED RUNNER ERROR: {e}", level="ERROR")
        return results_accumulator

    for res in results_accumulator:
        res['setup_time'] = setup_time; res['cleanup_time'] = cleanup_time; res['vram_prior'] = prior_vram
        # Ensure model field is populated for lifecycle failures
        if res.get('name') in ["LIFECYCLE", "SETUP"]:
            if domain == "stt": res["stt_model"] = model_display
            elif domain == "tts": res["tts_model"] = model_display
            else: res["llm_model"] = model_display
    
    utils.report_scenario_result = original_report_scenario
    utils.report_llm_result = original_report_llm
    return results_accumulator

def main():
    parser = argparse.ArgumentParser(description="Jarvis Plan-Driven Test Runner")
    parser.add_argument("plan", type=str, help="Path to a .yaml test plan (e.g., tests/plan_fast_check.yaml)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip stale artifact cleanup at start")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode (no models, simulated data)")
    args = parser.parse_args()

    # 1. Resolve and Initialize Session
    plan_path = resolve_path(args.plan)
    if not os.path.exists(plan_path):
        print(f"❌ ERROR: Plan not found at {plan_path}"); return
    
    session_dir, session_id = init_session(plan_path)
    if args.mock:
        with open(os.path.join(session_dir, "MOCK_RUN"), "w") as f: f.write("True")

    progression_logger = ProgressionLogger(session_dir)
    
    with open(plan_path, "r") as f:
        plan = yaml.safe_load(f)

    with open(os.path.join(session_dir, "system_info.yaml"), "r") as f:
        system_info = yaml.safe_load(f)

    # 2. Setup TUI Dashboard
    dashboard = RichDashboard(plan.get('name', 'Unnamed'), session_id, system_info)
    dashboard.vram_total = get_gpu_total_vram()
    
    # Pre-initialize structure
    structure = {}
    execution_blocks = plan.get('execution', [])
    for block in execution_blocks:
        d_name = block['domain'].lower()
        scenarios = load_scenarios(d_name, block.get('scenarios'))
        loadouts = block.get('loadouts', [])
        
        # If domain appears multiple times, append total
        if d_name not in structure:
            structure[d_name] = {
                "status": "pending", "done": 0, "total": 0, "models_done": 0,
                "start_time": None, "duration": 0,
                "loadouts": {}
            }
        
        structure[d_name]['total'] += len(scenarios) * len(loadouts)
        for models in loadouts:
            s_name = "_".join([m.replace(":", "-").replace("/", "--") for m in models])
            structure[d_name]['loadouts'][s_name] = {
                "status": "pending", "done": 0, "total": len(scenarios),
                "duration": 0, "errors": 0, "phase": None,
                "models": models
            }
    
    dashboard.init_plan_structure(structure)
    dashboard.start()

    try:
        progression_logger.log(f"Starting Test Plan: {plan.get('name')}")
        
        # 4. Execute Execution Blocks
        settings = plan.get('settings', {})
        
        for block in execution_blocks:
            domain = block['domain']
            dashboard.current_domain = domain.upper()
            # progression_logger.log(f"Switching to Domain: {domain.upper()}")
            
            scenarios = load_scenarios(domain, block.get('scenarios'))
            loadouts = block.get('loadouts', [])
            
            for models in loadouts:
                s_name = "_".join([m.replace(":", "-").replace("/", "--") for m in models])
                dashboard.current_loadout = s_name
                
                # Setup phase
                dashboard.update_phase(domain, s_name, "setup", "wip")
                
                def dashboard_capture(res):
                    dashboard.update_scenario(domain, s_name, res['name'], res['status'])

                start_l = time.perf_counter()
                res = run_domain_tests(
                    domain, s_name, models, scenarios, settings, 
                    session_dir, progression_logger, dashboard, mock=args.mock,
                    on_scenario=dashboard_capture,
                    on_phase=lambda p: dashboard.update_phase(domain, s_name, p)
                )
                
                status = "PASSED" if res and not any(r.get('status') == "FAILED" for r in res) else "FAILED"
                if res and any(r.get('status') == "MISSING" for r in res): status = "MISSING"
                
                # Incremental Save
                domain_results = [{"loadout": s_name, "scenarios": res or [], "status": status}]
                save_artifact(domain, domain_results, session_dir=session_dir)
                
                dashboard.finalize_loadout(domain, s_name, time.perf_counter() - start_l)
                
                if args.mock:
                    import random
                    dashboard.vram_usage = random.uniform(2.0, 24.0)
                else:
                    dashboard.vram_usage = get_gpu_vram_usage()

            dashboard.finalize_domain(domain)

        progression_logger.log("Plan execution complete.")
        dashboard.current_status = "Generating Report..."
        
        # 5. Finalize
        dashboard.current_status = "Generating Report..."
        report_path = trigger_report_generation(upload=True, session_dir=session_dir)
        dashboard.report_url = report_path
        dashboard.current_status = "Finished"
        time.sleep(1) 
        
    finally:
        dashboard.stop()
        print(f"\n✅ Session Complete: {session_id}")
        print(f"📁 Artifacts: {session_dir}")
        if report_path:
            print(f"📊 Report: {report_path}")

if __name__ == "__main__":
    main()
