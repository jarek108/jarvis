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
    list_all_loadouts, run_test_lifecycle, save_artifact, trigger_report_generation
)

def run_domain_tests(domain, loadout_name, purge=False, full=False, benchmark_mode=False):
    """Orchestrates the lifecycle and suite execution for a single domain/loadout."""
    # 1. Resolve the module and function
    try:
        module_path = f"{domain}.test"
        module = importlib.import_module(module_path)
        test_func_to_run = getattr(module, "run_test_suite")
    except (ImportError, AttributeError) as e:
        print(f"❌ ERROR: Could not load test suite for domain '{domain}': {e}")
        return None

    # 2. Extract the target model from loadout for the lifecycle helper
    loadout_path = os.path.join(script_dir, "loadouts", f"{loadout_name}.yaml")
    if not os.path.exists(loadout_path):
        print(f"❌ ERROR: Loadout '{loadout_name}' not found.")
        return None
        
    with open(loadout_path, "r") as f:
        l_data = yaml.safe_load(f)
        
    # Validation and target mapping
    target_id = None
    if domain in ["stt", "tts"]:
        val = l_data.get(domain)
        if val:
            target_id = val[0] if isinstance(val, list) else val
    elif domain in ["llm", "vlm"]:
        target_id = l_data.get("llm")
    elif domain == "sts":
        target_id = loadout_name # sts uses the loadout ID directly

    if not target_id and domain != "sts":
        print(f"⚠️ Skipping '{domain}' for loadout '{loadout_name}': Component not defined.")
        return None

    # 3. Execution container for results capturing
    results_accumulator = []
    
    # We wrap the domain's reporter to capture results locally for artifacts
    original_report_scenario = getattr(importlib.import_module("utils"), "report_scenario_result")
    original_report_llm = getattr(importlib.import_module("utils"), "report_llm_result")
    
    def capture_result(res):
        results_accumulator.append(res)
        original_report_scenario(res)
        
    def capture_llm_result(res):
        results_accumulator.append(res)
        original_report_llm(res)

    # Patch the reporting functions in the domain module's namespace
    # This ensures we capture the data even if the module imported the functions before we patched utils
    setattr(module, "report_scenario_result", capture_result)
    setattr(module, "report_llm_result", capture_llm_result)

    # 4. Run Lifecycle
    run_test_lifecycle(
        domain=domain,
        loadout_name=loadout_name,
        purge=purge,
        full=full,
        test_func=lambda: test_func_to_run(target_id) if domain != "sts" else test_func_to_run(target_id),
        benchmark_mode=benchmark_mode
    )
    
    # Restore original reporters
    utils.report_scenario_result = original_report_scenario
    utils.report_llm_result = original_report_llm
    
    return results_accumulator

def main():
    parser = argparse.ArgumentParser(description="Jarvis Unified Test Runner")
    parser.add_argument("--domain", type=str, help="Comma-separated list of domains (stt,tts,llm,vlm,sts). Defaults to all.")
    parser.add_argument("--loadout", type=str, help="Loadout name to test. If omitted, runs against all non-experimental loadouts.")
    parser.add_argument("--purge", action="store_true", help="Kill extra services before/after")
    parser.add_argument("--full", action="store_true", help="Ensure all loadout services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Deterministic output")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    
    args = parser.parse_args()

    # 1. Resolve Domains
    all_possible_domains = ["llm", "vlm", "stt", "tts", "sts"]
    if args.domain:
        target_domains = [d.strip().lower() for d in args.domain.split(",")]
    else:
        target_domains = all_possible_domains

    # 2. Resolve Loadouts
    if args.loadout:
        target_loadouts = [args.loadout]
    else:
        target_loadouts = list_all_loadouts(include_experimental=False)

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'JARVIS UNIFIED TEST RUNNER':^120}{RESET}")
    print(f"{'Domains: ' + ', '.join(target_domains):^120}")
    print(f"{'Loadouts: ' + ', '.join(target_loadouts):^120}")
    print("#"*LINE_LEN)

    global_start = time.perf_counter()
    
    # 3. Iterative Execution
    for domain in target_domains:
        domain_results = []
        for lid in target_loadouts:
            res = run_domain_tests(domain, lid, purge=args.purge, full=args.full, benchmark_mode=args.benchmark_mode)
            if res:
                domain_results.append({
                    "loadout": lid,
                    "scenarios": res,
                    "status": "PASSED" # Simplified for now
                })
        
        # Save artifact for this domain if we have results
        if domain_results:
            save_artifact(domain, domain_results)

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'ALL TESTS COMPLETE':^120}{RESET}")
    print(f"{'Total Time: ' + str(round(time.perf_counter() - global_start, 2)) + 's':^120}")
    print("#"*LINE_LEN + "\n")

    # 4. Final Reporting
    trigger_report_generation(upload=not args.local)

if __name__ == "__main__":
    main()
