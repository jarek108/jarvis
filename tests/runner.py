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

def run_domain_tests(domain, setup_name, models, purge_on_entry=True, purge_on_exit=True, full=False, benchmark_mode=True, force_download=False, track_prior_vram=True):
    """
    Orchestrates the lifecycle and suite execution for a single domain/setup.

    Args:
        domain (str): The test domain to run (e.g., 'stt', 'tts', 'llm', 'vlm', 'sts').
        setup_name (str): The specific setup identifier defined in the domain's test_setups.yaml.
        models (list): A list of model strings/IDs required for this specific test setup.
        purge_on_entry (bool): If True, performs a targeted cleanup of foreign Jarvis services before the test.
        purge_on_exit (bool): If True, performs a global cleanup of all Jarvis services after the test.
        full (bool): If True, ensures all services listed in the setup are started, even if not strictly required by the domain.
        benchmark_mode (bool): If True, enables extra telemetry and deterministic behavior for performance analysis.
        force_download (bool): If True, allows the system to automatically pull missing models from Ollama/vLLM providers.
        track_prior_vram (bool): If True, performs a full global cleanup before measurement to capture a clean baseline.

    Returns:
        list: A list of result dictionaries for each scenario executed in the test suite.
    """
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
        setup_time, cleanup_time, prior_vram = run_test_lifecycle(
            domain=domain,
            setup_name=setup_name,
            models=models,
            purge_on_entry=purge_on_entry,
            purge_on_exit=purge_on_exit,
            full=full,
            test_func=lambda: test_func_to_run(target_id), 
            benchmark_mode=benchmark_mode,
            force_download=force_download,
            track_prior_vram=track_prior_vram
        )
    except RuntimeError as e:
        print(f"❌ LIFECYCLE ERROR: {e}")
        from utils import report_scenario_result
        res_obj = {"name": "LIFECYCLE", "status": "FAILED", "duration": 0, "result": str(e), "mode": domain.upper(), "vram_prior": 0.0}
        report_scenario_result(res_obj)
        return results_accumulator # Return what we have (even if just the failure)

    # Inject lifecycle timings into results
    for res in results_accumulator:
        res['setup_time'] = setup_time
        res['cleanup_time'] = cleanup_time
        res['vram_prior'] = prior_vram
    
    # Restore original reporters (optional but good practice)
    utils.report_scenario_result = original_report_scenario
    utils.report_llm_result = original_report_llm
    
    return results_accumulator

def main():
    """
    Main entry point for the Jarvis Unified Test Runner.

    Handles CLI argument parsing, environment setup, stale artifact cleanup, 
    and iterative execution of test domains. Triggers final report generation 
    and optional cloud upload upon completion.
    """
    parser = argparse.ArgumentParser(description="Jarvis Unified Test Runner")
    parser.add_argument("--domain", type=str, help="Comma-separated list of domains (stt,tts,llm,vlm,sts). Defaults to all.")
    parser.add_argument("--setup", type=str, help="Comma-separated specific setup names from test_setups.yaml.")
    
    # Strict Defaults & Opt-Outs
    parser.add_argument("--keep-alive", action="store_true", help="Disable default exit purge (Keep models resident)")
    parser.add_argument("--dirty", action="store_true", help="Disable entry purge and VRAM tracking (Fast iteration)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip stale artifact cleanup at start")
    parser.add_argument("--force-download", action="store_true", help="Allow model downloads if missing (Default: False)")
    
    parser.add_argument("--full", action="store_true", help="Ensure all setup services are running")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    
    args = parser.parse_args()

    # Resolve Logic
    purge_on_entry = not args.dirty
    track_prior_vram = not args.dirty
    purge_on_exit = not args.keep_alive
    benchmark_mode = True # Always on

    # 0. Clean up stale "latest" artifacts to ensure the report only contains current run data
    if not args.no_cleanup:
        artifacts_dir = os.path.join(script_dir, "artifacts")
        if os.path.exists(artifacts_dir):
            for f in os.listdir(artifacts_dir):
                if f.startswith("latest_") and f.endswith(".json"):
                    try:
                        p = os.path.join(artifacts_dir, f)
                        os.remove(p)
                        print(f"🧹 Removed stale artifact: {f}")
                    except Exception as e:
                        print(f"⚠️ Failed to remove old artifact {f}: {e}")

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
            target_setups = {}
            requested_setups = [s.strip() for s in args.setup.split(",")]
            for rs in requested_setups:
                if rs in setups:
                    target_setups[rs] = setups[rs]
            
            if not target_setups:
                print(f"⚠️ Skipping domain '{domain}': None of the requested setups {requested_setups} found.")
                continue
        else:
            target_setups = setups

        for s_name, models in target_setups.items():
            try:
                res = run_domain_tests(
                    domain, s_name, models, 
                    purge_on_entry=purge_on_entry,
                    purge_on_exit=purge_on_exit,
                    full=args.full, 
                    benchmark_mode=benchmark_mode,
                    force_download=args.force_download,
                    track_prior_vram=track_prior_vram
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
