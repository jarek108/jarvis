import argparse
import sys
import os
import time
import json
import yaml
import importlib
import utils

# Add project root and tests root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(script_dir)
sys.path.append(project_root)

from utils import (
    CYAN, BOLD, RESET, LINE_LEN, 
    run_test_lifecycle, save_artifact, trigger_report_generation,
    resolve_path
)

def load_scenarios(domain, filter_list=None):
    """Loads scenarios from domain/scenarios.yaml and filters if requested."""
    path = os.path.join(script_dir, domain, "scenarios.yaml")
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    
    # Convert dict to list of named objects
    all_scenarios = [{"name": k, **v} for k, v in data.items()]
    
    if not filter_list or "all" in filter_list:
        return all_scenarios
    
    return [s for s in all_scenarios if s['name'] in filter_list]

def run_domain_tests(domain, setup_name, models, scenarios, settings):
    """Orchestrates the lifecycle and suite execution for a single domain/setup."""
    try:
        module_path = f"{domain}.test"
        module = importlib.import_module(module_path)
        test_func_to_run = getattr(module, "run_test_suite")
    except (ImportError, AttributeError) as e:
        print(f"❌ ERROR: Could not load test suite for domain '{domain}': {e}")
        return None

    results_accumulator = []
    
    # Wrap domain's reporter to capture results locally
    original_report_scenario = getattr(importlib.import_module("utils"), "report_scenario_result")
    original_report_llm = getattr(importlib.import_module("utils"), "report_llm_result")
    
    def capture_result(res):
        results_accumulator.append(res); original_report_scenario(res)
    def capture_llm_result(res):
        results_accumulator.append(res); original_report_llm(res)

    setattr(module, "report_scenario_result", capture_result)
    setattr(module, "report_llm_result", capture_llm_result)

    # Resolve target ID for domain
    target_id = setup_name
    for m in models:
        if domain == "stt" and m in utils.load_config()['stt_loadout']: target_id = m; break
        if domain == "tts" and m in utils.load_config()['tts_loadout']: target_id = m; break
        if domain in ["llm", "vlm"] and (":" in m or "/" in m or m.startswith("vllm:")): target_id = m; break

    try:
        setup_time, cleanup_time, prior_vram = run_test_lifecycle(
            domain=domain, setup_name=setup_name, models=models,
            purge_on_entry=settings.get('purge_on_entry', True),
            purge_on_exit=settings.get('purge_on_exit', True),
            full=settings.get('full', False),
            test_func=lambda: test_func_to_run(target_id, scenarios_to_run=scenarios), 
            benchmark_mode=True,
            force_download=settings.get('force_download', False),
            track_prior_vram=settings.get('track_prior_vram', True)
        )
    except Exception as e:
        print(f"❌ LIFECYCLE ERROR: {e}")
        from utils import report_scenario_result
        res_obj = {"name": "LIFECYCLE", "status": "FAILED", "duration": 0, "result": str(e), "mode": domain.upper(), "vram_prior": 0.0}
        report_scenario_result(res_obj); return results_accumulator

    for res in results_accumulator:
        res['setup_time'] = setup_time; res['cleanup_time'] = cleanup_time; res['vram_prior'] = prior_vram
    
    utils.report_scenario_result = original_report_scenario
    utils.report_llm_result = original_report_llm
    return results_accumulator

def main():
    parser = argparse.ArgumentParser(description="Jarvis Plan-Driven Test Runner")
    parser.add_argument("--plan", type=str, required=True, help="Path to a .yaml test plan (e.g., tests/plan_fast_check.yaml)")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip stale artifact cleanup at start")
    args = parser.parse_args()

    # 1. Resolve the Plan
    plan_path = resolve_path(args.plan)
    if not os.path.exists(plan_path):
        print(f"❌ ERROR: Plan not found at {plan_path}"); return
    with open(plan_path, "r") as f:
        plan = yaml.safe_load(f)

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'JARVIS TEST PLAN: ' + plan.get('name', 'Unnamed'):^120}{RESET}")
    print("#"*LINE_LEN)

    # 0. Cleanup stale artifacts
    if not args.no_cleanup:
        artifacts_dir = os.path.join(script_dir, "artifacts")
        if os.path.exists(artifacts_dir):
            for f in os.listdir(artifacts_dir):
                if f.startswith("latest_") and f.endswith(".json"):
                    os.remove(os.path.join(artifacts_dir, f))

    # 2. Execute Execution Blocks
    global_start = time.perf_counter()
    settings = plan.get('settings', {})
    
    # Store results by domain for final artifact saving
    all_results = {}

    for block in plan.get('execution', []):
        domain = block['domain']
        if domain not in all_results: all_results[domain] = []
        
        scenarios = load_scenarios(domain, block.get('scenarios'))
        
        # Resolve Setups
        setup_path = os.path.join(script_dir, domain, "test_setups.yaml")
        with open(setup_path, "r") as f: setups = yaml.safe_load(f)
        
        target_setups = {k: v for k, v in setups.items() if k in block.get('loadouts', [])} if block.get('loadouts') else setups

        for s_name, models in target_setups.items():
            res = run_domain_tests(domain, s_name, models, scenarios, settings)
            status = "PASSED" if res and not any(r.get('status') == "FAILED" for r in res) else "FAILED"
            if res and any(r.get('status') == "MISSING" for r in res): status = "MISSING"
            
            all_results[domain].append({"loadout": s_name, "scenarios": res or [], "status": status})

    # 3. Save and Report
    for domain, domain_res in all_results.items():
        if domain_res: save_artifact(domain, domain_res)

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'PLAN COMPLETE':^120}{RESET}")
    print(f"{'Total Time: ' + str(round(time.perf_counter() - global_start, 2)) + 's':^120}")
    print("#"*LINE_LEN + "\n")

    trigger_report_generation(upload=not args.local)

if __name__ == "__main__":
    main()
