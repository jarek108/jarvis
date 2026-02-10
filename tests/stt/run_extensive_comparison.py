import os
import sys
import time
import subprocess
import json

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, BOLD, RESET, LINE_LEN, RED, list_all_stt_models

def run_stt_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # DYNAMIC DISCOVERY
    models = list_all_stt_models()
    
    suite_results = []
    total_start = time.perf_counter()
    python_exe = sys.executable
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'STT MULTI-MODEL ONE-TO-ONE COMPARISON':^120}{RESET}")
    print("#"*LINE_LEN)

    for mid in models:
        print(f"\n>>> Benchmarking Model: {mid.upper()}")
        script_path = os.path.join(base_dir, "run_isolated.py")
        
        try:
            process = subprocess.run([python_exe, script_path, "--model", mid, "--benchmark-mode"], env=env, capture_output=True, text=True, encoding='utf-8')
            
            scenarios = []
            for line in process.stdout.splitlines():
                if line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                else:
                    if line.strip() and not line.startswith("LIFECYCLE_RECEIPT"):
                        print(f"  {line}")

            suite_results.append({
                "model_id": mid,
                "status": "PASSED" if scenarios else "FAILED",
                "scenarios": scenarios
            })
        except Exception as e:
            print(f"Error running {mid}: {e}")

    # --- PIVOT DATA BY SCENARIO ---
    pivoted_data = {} 
    all_scenario_names = []
    for suite in suite_results:
        for s in suite['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][suite['model_id']] = s

    # --- FINAL CONSOLIDATED REPORT ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'STT MULTI-MODEL CONSOLIDATED PERFORMANCE REPORT':^120}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        print(f"  {'Model':<30} | {'Status':<8} | {'Time':<8} | {'Details'}")
        print(f"  {'-'*30} | {'-'*8} | {'-'*8} | {'-'*60}")
        
        for mid in models:
            s_res = pivoted_data[name].get(mid)
            if s_res:
                print(f"  {mid:<30} | {format_status(s_res['status']):<17} | {s_res['duration']:.2f}s | {s_res['result']}")
            else:
                print(f"  {mid:<30} | {RED}{'MISSING':<8}{RESET} | {'-':<8} | N/A")

    print("\n" + "="*LINE_LEN)
    print(f"Total STT Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_stt_suite()