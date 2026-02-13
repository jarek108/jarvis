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
    run_test_lifecycle, save_artifact, trigger_report_generation
)

def run_domain_tests(domain, setup_name, models, purge=False, full=False, benchmark_mode=False, force_download=False):
    """Orchestrates the lifecycle and suite execution for a single domain/setup."""
    # 1. Resolve the module and function
    try:
        module_path = f"{domain}.test"
        module = importlib.import_module(module_path)
        test_func_to_run = getattr(module, "run_test_suite")
    except (ImportError, AttributeError) as e:
        print(f"❌ ERROR: Could not load test suite for domain '{domain}': {e}")
        return None

    # 2. Execution container for results capturing
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
    setattr(module, "report_scenario_result", capture_result)
    setattr(module, "report_llm_result", capture_llm_result)

    # 3. Resolve the relevant model for this domain from the list
    # LifecycleManager has this logic, let's use a helper or local logic
    target_id = setup_name # default fallback
    for m in models:
        if domain == "stt" and m in utils.load_config()['stt_loadout']:
            target_id = m
            break
        if domain == "tts" and m in utils.load_config()['tts_loadout']:
            target_id = m
            break
        if domain in ["llm", "vlm"] and (":" in m or "/" in m or m.startswith("vllm:")):
            # We keep the prefix so test.py knows which engine to use
            target_id = m
            break

    # 4. Run Lifecycle
    try:
        setup_time, cleanup_time = run_test_lifecycle(
            domain=domain,
            setup_name=setup_name,
            models=models,
            purge=purge,
            full=full,
            test_func=lambda: test_func_to_run(target_id), 
            benchmark_mode=benchmark_mode,
            force_download=force_download
        )
    except RuntimeError as e:
        print(f"❌ LIFECYCLE ERROR: {e}")
        from utils import report_scenario_result
        res_obj = {"name": "LIFECYCLE", "status": "FAILED", "duration": 0, "result": str(e), "mode": domain.upper()}
        report_scenario_result(res_obj)
        return results_accumulator # Return what we have (even if just the failure)

    # Inject lifecycle timings into results
    for res in results_accumulator:
        res['setup_time'] = setup_time
        res['cleanup_time'] = cleanup_time
    
    # Restore original reporters (optional but good practice)
    utils.report_scenario_result = original_report_scenario
    utils.report_llm_result = original_report_llm
    
    return results_accumulator

def main():
    parser = argparse.ArgumentParser(description="Jarvis Unified Test Runner")
    parser.add_argument("--domain", type=str, help="Comma-separated list of domains (stt,tts,llm,vlm,sts). Defaults to all.")
    parser.add_argument("--setup", type=str, help="Specific setup name from test_setups.yaml to test.")
    parser.add_argument("--purge", action="store_true", help="Kill extra services before/after")
    parser.add_argument("--full", action="store_true", help="Ensure all setup services are running")
    parser.add_argument("--benchmark-mode", action="store_true", help="Deterministic output")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    parser.add_argument("--force-download", action="store_true", help="Allow model downloads if missing")
    
    args = parser.parse_args()

    # 1. Resolve Domains
    all_possible_domains = ["llm", "vlm", "stt", "tts", "sts"]
    if args.domain:
        target_domains = [d.strip().lower() for d in args.domain.split(",")]
    else:
        target_domains = all_possible_domains

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'JARVIS UNIFIED TEST RUNNER':^120}{RESET}")
    print(f"{'Domains: ' + ', '.join(target_domains):^120}")
    print("#"*LINE_LEN)

    global_start = time.perf_counter()
    
    # 2. Iterative Execution
    for domain in target_domains:
        domain_results = []
        
        # Load test_setups.yaml for this domain
        setup_path = os.path.join(script_dir, domain, "test_setups.yaml")
        if not os.path.exists(setup_path):
            print(f"⚠️ Skipping domain '{domain}': test_setups.yaml not found at {setup_path}")
            continue
            
        with open(setup_path, "r") as f:
            setups = yaml.safe_load(f)
            
        if not setups:
            print(f"⚠️ Skipping domain '{domain}': No setups defined in test_setups.yaml")
            continue

        # Filter by specific setup if requested
        if args.setup:
            if args.setup in setups:
                target_setups = {args.setup: setups[args.setup]}
            else:
                print(f"❌ ERROR: Setup '{args.setup}' not found in {domain}/test_setups.yaml")
                continue
        else:
            target_setups = setups

        for s_name, models in target_setups.items():
            try:
                res = run_domain_tests(
                    domain, s_name, models, 
                    purge=args.purge, 
                    full=args.full, 
                    benchmark_mode=args.benchmark_mode,
                    force_download=args.force_download
                )
                
                status = "PASSED"
                if not res:
                    status = "FAILED"
                elif any(isinstance(r, dict) and r.get('status') == "MISSING" for r in res):
                    status = "MISSING"

                domain_results.append({
                    "loadout": s_name, 
                    "scenarios": res or [],
                    "status": status
                })
            except Exception as e:
                print(f"❌ CRITICAL SUITE ERROR for {domain}/{s_name}: {e}")
                import traceback
                traceback.print_exc()
        
        # Save artifact for this domain if we have results
        if domain_results:
            save_artifact(domain, domain_results)

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'ALL TESTS COMPLETE':^120}{RESET}")
    print(f"{'Total Time: ' + str(round(time.perf_counter() - global_start, 2)) + 's':^120}")
    print("#"*LINE_LEN + "\n")

    # 3. Final Reporting
    trigger_report_generation(upload=not args.local)

if __name__ == "__main__":
    main()
