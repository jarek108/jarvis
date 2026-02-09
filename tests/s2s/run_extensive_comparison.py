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

    python_exe = sys.executable
    
    LINE_LEN = 140

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'S2S MULTI-LOADOUT PIPELINE BENCHMARK':^140}{RESET}")
    print("#"*LINE_LEN)

    # Resolve project root (one level up from tests/s2s)
    project_root = os.path.dirname(os.path.dirname(base_dir))

    for lid in loadouts:
        print(f"\n>>> Running Loadout: {lid.upper()}")
        isolated_script = os.path.join(base_dir, f"isolated_{lid}.py")
        
        # Add tests root and project root to PYTHONPATH
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + os.pathsep + os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

        try:
            # Capture output
            process = subprocess.run([python_exe, isolated_script, "--benchmark-mode"], env=env, capture_output=True, text=True, encoding='utf-8')
            
            receipt = {}
            scenarios = []
            for line in process.stdout.splitlines():
                is_machine = line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ")
                if line.startswith("LIFECYCLE_RECEIPT: "):
                    receipt = json.loads(line.replace("LIFECYCLE_RECEIPT: ", ""))
                elif line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                
                if not is_machine and line.strip():
                    # Print regular progress lines (only if they aren't empty)
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
    pivoted_data = {} # {scenario_name: {loadout_id: {"WAV": res, "STREAM": res}}}
    all_scenario_names = []
    
    for suite in suite_results:
        lid = suite['loadout']
        for s in suite['scenarios']:
            name = s['name']
            mode = s.get('mode', 'WAV')
            if name not in pivoted_data:
                pivoted_data[name] = {}
                all_scenario_names.append(name)
            
            if lid not in pivoted_data[name]:
                pivoted_data[name][lid] = {}
            
            pivoted_data[name][lid][mode] = s

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'S2S MULTI-LOADOUT CONSOLIDATED HEALTH REPORT':^140}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        for lid in loadouts:
            modes_data = pivoted_data[name].get(lid, {})
            
            # Print WAV if exists
            if "WAV" in modes_data:
                s_res = modes_data["WAV"]
                metrics = f"STT:{s_res['stt_inf']:.2f}s | LLM:{s_res['llm_tot']:.2f}s | TTS:{s_res['tts_inf']:.2f}s"
                print(f"  {format_status(s_res['status'])} {lid:<25} | WAV     | Total:{s_res['duration']:.2f}s | {metrics}")
                # Breakdown
                print(f"    \t🎙️ {s_res['stt_inf']:.2f}s | [{s_res['stt_model']}] | Text: \"{s_res['stt_text']}\"")
                print(f"    \t🧠 {s_res['llm_tot']:.2f}s | [{s_res['llm_model']}] | Text: \"{s_res['llm_text']}\"")
                print(f"    \t🔊 {s_res['tts_inf']:.2f}s | [{s_res['tts_model']}] | Path: {s_res['result']}")

            # Print STREAM if exists
            if "STREAM" in modes_data:
                s_res = modes_data["STREAM"]
                m = s_res.get('metrics', {})
                def fmt_range(key):
                    r = m.get(key, [0, 0])
                    return f"{r[0]:.2f}→{r[1]:.2f}s"
                metrics = f"STT:{fmt_range('stt')} | LLM:{fmt_range('llm')} | TTS:{fmt_range('tts')}"
                print(f"  {format_status(s_res['status'])} {lid:<25} | STREAM  | {metrics}")
                # Breakdown
                print(f"    \t🎙️ {fmt_range('stt')} | [{s_res.get('stt_model', 'STT')}] | Text: \"{m.get('stt_text', 'N/A')}\"")     
                print(f"    \t🧠 {fmt_range('llm')} | [{s_res.get('llm_model', 'LLM')}] | Text: \"{m.get('llm_text', 'N/A').strip()}\"")
                print(f"    \t🔊 {fmt_range('tts')} | [{s_res.get('tts_model', 'TTS')}] | Path: {s_res['result']}")
            
            if not modes_data:
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