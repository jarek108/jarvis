import os
import sys
import time
import subprocess
import json

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, BOLD, RESET, LINE_LEN, RED

def run_stt_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    whisper_dir = os.path.join(base_dir, "whisper")
    sizes = ["faster-whisper-tiny", "faster-whisper-base", "faster-whisper-small", "faster-whisper-medium", "faster-whisper-large"]
    
    suite_results = []
    total_start = time.perf_counter()

    python_exe = os.path.join(os.path.dirname(os.path.dirname(base_dir)), "jarvis-venv", "Scripts", "python.exe")
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'WHISPER MULTI-SIZE BENCHMARK RUN':^120}{RESET}")
    print("#"*LINE_LEN)

    for size_id in sizes:
        print(f"\n>>> Loading Model: {size_id.upper()}")
        short_name = size_id.replace("faster-whisper-", "")
        isolated_script = os.path.join(whisper_dir, f"isolated_{short_name}.py")
        
        try:
            # Capture output so we can parse and filter
            process = subprocess.run([python_exe, isolated_script], env=env, capture_output=True, text=True, encoding='utf-8')
            
            scenarios = []
            receipt = {}
            for line in process.stdout.splitlines():
                if line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                elif line.startswith("LIFECYCLE_RECEIPT: "):
                    receipt = json.loads(line.replace("LIFECYCLE_RECEIPT: ", ""))
                else:
                    # Print only human-readable progress
                    print(line)

            suite_results.append({
                "size": size_id,
                "status": "PASSED" if process.returncode == 0 and scenarios else "FAILED",
                "scenarios": scenarios,
                "receipt": receipt
            })
        except Exception as e:
            print(f"Error running {size_id}: {e}")
            suite_results.append({"size": size_id, "status": "FAILED", "scenarios": [], "receipt": {}})

    # --- PIVOT DATA BY SAMPLE ---
    pivoted_data = {}
    all_scenario_names = []
    for suite in suite_results:
        for s in suite['scenarios']:
            name = s['name']
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            pivoted_data[name][suite['size']] = s

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'STT MULTI-SIZE CONSOLIDATED HEALTH REPORT':^120}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Sample: {name}{RESET}")
        for size_id in sizes:
            s_res = pivoted_data[name].get(size_id)
            if s_res:
                print(f"  \t{format_status(s_res['status'])} {size_id:<25} | {s_res['duration']:.2f}s | {s_res['result']}")
            else:
                print(f"  \t{RED}[MISSING]{RESET} {size_id:<25} | N/A")

    print("\n" + "-"*LINE_LEN)
    print(f"{BOLD}Infrastructure Lifecycle (Setup/Cleanup Time):{RESET}")
    for res in suite_results:
        r = res['receipt']
        time_str = f"Setup: {r.get('setup',0):.1f}s | Cleanup: {r.get('cleanup',0):.1f}s"
        print(f"  {res['size']:<25}: {time_str}")

    print("="*LINE_LEN)
    print(f"Total STT Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_stt_suite()