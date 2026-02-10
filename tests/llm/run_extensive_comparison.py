import os
import sys
import time
import subprocess
import json

# Allow importing utils from parent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, GREEN, RED, BOLD, RESET, LINE_LEN, list_all_llm_models

def run_llm_comparison():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # DYNAMIC DISCOVERY
    models = list_all_llm_models()
    
    suite_results = []
    total_start = time.perf_counter()
    python_exe = sys.executable
    
    project_root = os.path.dirname(os.path.dirname(base_dir))
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'LLM MULTI-MODEL ONE-TO-ONE COMPARISON BENCHMARK':^120}{RESET}")
    print("#"*LINE_LEN)

    for mid in models:
        print(f"\n>>> Benchmarking Model: {mid.upper()}")
        script_path = os.path.join(base_dir, "run_isolated.py")
        
        try:
            process = subprocess.run([python_exe, script_path, "--model", mid], env=env, capture_output=True, text=True, encoding='utf-8')
            
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
                "model_id": mid,
                "scenarios": scenarios,
                "vram": vram_audit,
                "status": "PASSED" if scenarios else "FAILED"
            })
        except Exception as e:
            print(f"Error benchmarking {mid}: {e}")

    # --- PIVOT DATA BY SCENARIO ---
    pivoted_data = {} 
    all_scenario_names = []
    for res in suite_results:
        for s in res['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][res['model_id']] = s

    # --- FINAL CONSOLIDATED REPORT ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'LLM ONE-TO-ONE COMPARISON REPORT (SPEED & MEMORY)':^120}{RESET}")
    print("="*LINE_LEN)

    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        print(f"  {'Model':<40} | {'TTFT':<8} | {'TTFR':<8} | {'TPS':<6} | {'VRAM Peak':<10} | {'Placement'}")
        print(f"  {'-'*40} | {'-'*8} | {'-'*8} | {'-'*6} | {'-'*10} | {'-'*15}")
        
        for mid in models:
            s_res = pivoted_data[name].get(mid)
            m_res = next((r for r in suite_results if r['model_id'] == mid), {})
            vram = m_res.get('vram', {})
            
            if s_res and s_res['status'] == "PASSED":
                v_peak = f"{vram.get('peak_gb', 0):.1f} GB"
                placement = f"{GREEN}FULL VRAM{RESET}" if vram.get('is_ok') else f"{RED}🚨 SWAP{RESET}"
                print(f"  {mid:<40} | {s_res['ttft']:.3f}s | {s_res['ttfr']:.3f}s | {s_res['tps']:>5.1f} | {v_peak:<10} | {placement}")
            else:
                print(f"  {mid:<40} | {'FAILED':<8} | {'-':<8} | {'-':<6} | {'-':<10} | {'-'}")

    print("\n" + "="*LINE_LEN)
    print(f"Total Comparison Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_llm_comparison()