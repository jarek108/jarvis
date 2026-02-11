import os
import sys
import time
import subprocess
import json
import yaml

# Allow importing utils from parent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, GREEN, RED, BOLD, RESET, LINE_LEN, list_all_loadouts

def run_vlm_comparison():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    loadouts = list_all_loadouts()
    
    suite_results = []
    total_start = time.perf_counter()
    python_exe = sys.executable
    
    project_root = os.path.dirname(os.path.dirname(base_dir))
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'VLM MULTI-LOADOUT VISION COMPARISON BENCHMARK':^120}{RESET}")
    print("#"*LINE_LEN)

    vlm_loadouts = []
    for lid in loadouts:
        path = os.path.join(project_root, "tests", "loadouts", f"{lid}.yaml")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                llm = data.get("llm", "").lower()
                # Run if 'vision: true' IS explicitly set OR if name contains 'vl' and vision IS NOT false
                has_vision_flag = data.get("vision")
                if has_vision_flag is True or (has_vision_flag is not False and "vl" in llm):
                    vlm_loadouts.append(lid)
        except:
            pass

    for lid in vlm_loadouts:
        print(f"\n>>> Benchmarking VLM Loadout: {lid.upper()}")
        script_path = os.path.join(base_dir, "test.py")
        
        try:
            process = subprocess.run([python_exe, script_path, "--loadout", lid, "--purge"], env=env, capture_output=True, text=True, encoding='utf-8')
            
            scenarios = []
            vram_audit = {}
            for line in process.stdout.splitlines():
                if line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                elif line.startswith("VRAM_AUDIT_RESULT: "):
                    vram_audit = json.loads(line.replace("VRAM_AUDIT_RESULT: ", ""))
                else:
                    if line.strip() and not line.startswith("LIFECYCLE_RECEIPT"):
                        print(f"  {line}")

            suite_results.append({
                "loadout": lid,
                "scenarios": scenarios,
                "vram": vram_audit,
                "status": "PASSED" if scenarios else "FAILED"
            })
        except Exception as e:
            print(f"Error benchmarking {lid}: {e}")

    # --- PIVOT DATA BY SCENARIO ---
    pivoted_data = {} 
    all_scenario_names = []
    for res in suite_results:
        for s in res['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][res['loadout']] = s

    # --- FINAL CONSOLIDATED REPORT ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'VLM MULTI-LOADOUT VISION PERFORMANCE REPORT':^120}{RESET}")
    print("="*LINE_LEN)

    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        print(f"  {'Loadout':<40} | {'TTFT':<8} | {'TPS':<6} | {'VRAM Peak'}")
        print(f"  {'-'*40} | {'-'*8} | {'-'*6} | {'-'*10}")
        
        for lid in vlm_loadouts:
            s_res = pivoted_data[name].get(lid)
            m_res = next((r for r in suite_results if r['loadout'] == lid), {})
            vram = m_res.get('vram', {})
            
            if s_res and s_res['status'] == "PASSED":
                v_peak = f"{vram.get('peak_gb', 0):.1f} GB"
                print(f"  {lid:<40} | {s_res['ttft']:.3f}s | {s_res['tps']:>5.1f} | {v_peak:<10}")
            else:
                print(f"  {lid:<40} | {'FAILED':<8} | {'-':<6} | {'-':<10}")

    print("\n" + "="*LINE_LEN)
    print(f"Total VLM Comparison Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_vlm_comparison()
