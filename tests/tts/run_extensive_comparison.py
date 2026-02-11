import os
import sys
import time
import subprocess
import json
import argparse

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, BOLD, RESET, LINE_LEN, RED, list_all_loadouts, save_artifact, trigger_report_generation

def run_tts_comparison(upload=True):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    loadouts = list_all_loadouts()
    
    suite_results = []
    total_start = time.perf_counter()
    python_exe = sys.executable
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'TTS MULTI-LOADOUT COMPARISON BENCHMARK':^120}{RESET}")
    print("#"*LINE_LEN)

    for lid in loadouts:
        print(f"\n>>> Benchmarking Loadout: {lid.upper()}")
        script_path = os.path.join(base_dir, "test.py")
        
        try:
            process = subprocess.run([python_exe, script_path, "--loadout", lid, "--purge", "--benchmark-mode"], env=env, capture_output=True, text=True, encoding='utf-8')
            
            scenarios = []
            for line in process.stdout.splitlines():
                if line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                else:
                    if line.strip() and not line.startswith("LIFECYCLE_RECEIPT"):
                        print(f"  {line}")

            suite_results.append({
                "loadout": lid,
                "status": "PASSED" if scenarios else "FAILED",
                "scenarios": scenarios
            })
        except Exception as e:
            print(f"Error running {lid}: {e}")

    # --- PIVOT DATA BY SCENARIO ---
    pivoted_data = {} 
    all_scenario_names = []
    for suite in suite_results:
        for s in suite['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][suite['loadout']] = s

    # --- FINAL CONSOLIDATED REPORT ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'TTS MULTI-LOADOUT CONSOLIDATED PERFORMANCE REPORT':^120}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        print(f"  {'Loadout':<40} | {'Status':<8} | {'Time':<8} | {'Resulting Path'}")
        print(f"  {'-'*40} | {'-'*8} | {'-'*8} | {'-'*50}")
        
        for lid in loadouts:
            s_res = pivoted_data[name].get(lid)
            if s_res:
                print(f"  {lid:<40} | {format_status(s_res['status']):<17} | {s_res['duration']:.2f}s | {s_res['result']}")
            else:
                print(f"  {lid:<40} | {RED}{'MISSING':<8}{RESET} | {'-':<8} | N/A")

    print("\n" + "="*LINE_LEN)
    print(f"Total TTS Suite Time: {time.perf_counter() - total_start:.2f}s\n")
    
    save_artifact("tts", suite_results)
    trigger_report_generation(upload=upload)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TTS Extensive Comparison")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    args = parser.parse_args()
    run_tts_comparison(upload=not args.local)
