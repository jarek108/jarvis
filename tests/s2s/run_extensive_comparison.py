import os
import sys
import time
import subprocess
import json

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def run_s2s_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    loadouts = ["default", "turbo_ultra", "eng_accurate"]
    
    suite_results = []
    total_start = time.perf_counter()

    python_exe = os.path.join(os.path.dirname(os.path.dirname(base_dir)), "jarvis-venv", "Scripts", "python.exe")
    
    LINE_LEN = 140

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'S2S MULTI-LOADOUT PIPELINE BENCHMARK':^140}{RESET}")
    print("#"*LINE_LEN)

    for lid in loadouts:
        print(f"\n>>> Running Loadout: {lid.upper()}")
        isolated_script = os.path.join(base_dir, f"isolated_{lid}.py")
        
        try:
            # Capture output
            process = subprocess.run([python_exe, isolated_script], capture_output=True, text=True, encoding='utf-8')
            
            receipt = {}
            scenarios = []
            for line in process.stdout.splitlines():
                if line.startswith("LIFECYCLE_RECEIPT: "):
                    receipt = json.loads(line.replace("LIFECYCLE_RECEIPT: ", ""))
                elif line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                else:
                    # Print regular progress lines (only if they aren't empty)
                    if line.strip():
                        print(line)

            if process.stderr:
                print(process.stderr, file=sys.stderr)

            suite_results.append({
                "loadout": lid,
                "status": "PASSED" if process.returncode == 0 and scenarios else "FAILED",
                "receipt": receipt,
                "scenarios": scenarios
            })
        except Exception as e:
            print(f"Error running {lid}: {e}")
            suite_results.append({"loadout": lid, "status": "FAILED", "receipt": {}, "scenarios": []})

    # --- PIVOT DATA BY SAMPLE ---
    pivoted_data = {}
    all_scenario_names = []
    for suite in suite_results:
        for s in suite['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][suite['loadout']] = s

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'S2S MULTI-LOADOUT CONSOLIDATED HEALTH REPORT':^140}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        for lid in loadouts:
            s_res = pivoted_data[name].get(lid)
            if s_res:
                if s_res.get('stream'):
                    m = s_res.get('metrics', {})
                    def fmt_range(key):
                        r = m.get(key, [0, 0])
                        return f"{r[0]:.2f}→{r[1]:.2f}s"
                    metrics = f"STT:{fmt_range('stt')} | LLM:{fmt_range('llm')} | TTS:{fmt_range('tts')}"
                    print(f"  {format_status(s_res['status'])} {lid:<25} | Stream  | {metrics}")
                else:
                    metrics = f"STT:{s_res['stt_inf']:.2f}s | LLM:{s_res['llm_tot']:.2f}s | TTS:{s_res['tts_inf']:.2f}s"
                    print(f"  {format_status(s_res['status'])} {lid:<25} | Total:{s_res['duration']:.2f}s | {metrics}")
            else:
                print(f"  {RED}[MISSING]{RESET} {lid:<25} | N/A")

    print("\n" + "-"*LINE_LEN)
    print(f"{BOLD}Infrastructure Lifecycle (Setup/Cleanup Time):{RESET}")
    for res in suite_results:
        r = res['receipt']
        time_str = f"Setup: {r.get('setup',0):.1f}s | Processing: {r.get('processing',0):.1f}s | Cleanup: {r.get('cleanup',0):.1f}s"
        print(f"  {res['loadout']:<25}: {time_str}")

    print("="*LINE_LEN)
    print(f"Total S2S Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_s2s_suite()
