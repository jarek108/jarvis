import os
import sys
import time
import subprocess
import json

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, BOLD, RESET, LINE_LEN, RED, fmt_with_chunks, list_all_loadouts, save_artifact

def run_s2s_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # DYNAMIC DISCOVERY
    loadouts = list_all_loadouts()
    
    suite_results = []
    total_start = time.perf_counter()
    python_exe = sys.executable
    
    LINE_LEN = 145

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'S2S MULTI-LOADOUT ONE-TO-ONE COMPARISON':^145}{RESET}")
    print("#"*LINE_LEN)

    project_root = os.path.dirname(os.path.dirname(base_dir))

    for lid in loadouts:
        print(f"\n>>> Benchmarking Loadout: {lid.upper()}")
        script_path = os.path.join(base_dir, "test.py")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + os.pathsep + os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

        try:
            process = subprocess.run([python_exe, script_path, "--loadout", lid, "--benchmark-mode"], env=env, capture_output=True, text=True, encoding='utf-8')
            
            receipt = {}
            scenarios = []
            vram_audit = {}
            for line in process.stdout.splitlines():
                is_machine = line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ") or line.startswith("VRAM_AUDIT_RESULT: ")
                if line.startswith("LIFECYCLE_RECEIPT: "):
                    receipt = json.loads(line.replace("LIFECYCLE_RECEIPT: ", ""))
                elif line.startswith("SCENARIO_RESULT: "):
                    scenarios.append(json.loads(line.replace("SCENARIO_RESULT: ", "")))
                elif line.startswith("VRAM_AUDIT_RESULT: "):
                    vram_audit = json.loads(line.replace("VRAM_AUDIT_RESULT: ", ""))
                
                if not is_machine and line.strip():
                    print(f"  {line}")

            if process.stderr:
                print(process.stderr, file=sys.stderr)

            suite_results.append({
                "loadout": lid,
                "status": "PASSED" if scenarios else "FAILED",
                "receipt": receipt,
                "scenarios": scenarios,
                "vram": vram_audit
            })
        except Exception as e:
            print(f"Error running {lid}: {e}")
            suite_results.append({"loadout": lid, "status": "FAILED", "receipt": {}, "scenarios": [], "vram": {}})

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

    # --- FINAL CONSOLIDATED REPORT ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'S2S MULTI-LOADOUT CONSOLIDATED PERFORMANCE REPORT':^145}{RESET}")
    print("="*LINE_LEN)
    
    for name in all_scenario_names:
        print(f"\n{BOLD}Scenario: {name}{RESET}")
        print(f"  {'Loadout':<30} | {'Mode':<7} | {'Total/t1':<8} | {'STT Window':<12} | {'LLM Window':<12} | {'TTS Window':<12} | {'VRAM Peak'}")
        print(f"  {'-'*30} | {'-'*7} | {'-'*8} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*10}")
        
        for lid in loadouts:
            modes_data = pivoted_data[name].get(lid, {})
            # Find the VRAM data for this loadout
            loadout_res = next((r for r in suite_results if r['loadout'] == lid), {})
            vram_data = loadout_res.get('vram', {})
            v_peak = f"{vram_data.get('peak_gb', 0):.1f} GB" if vram_data else "N/A"

            for mode in ["WAV", "STREAM"]:
                s_res = modes_data.get(mode)
                if s_res and s_res['status'] == "PASSED":
                    if mode == "STREAM":
                        m = s_res.get('metrics', {})
                        t1 = m.get('tts', [0,0])[0]
                        def fmt_r(k): 
                            r = m.get(k, [0,0])
                            return f"{r[0]:>4.1f}→{r[1]:<4.1f}s"
                        
                        print(f"  {lid:<30} | {mode:<7} | {t1:>7.2f}s | {fmt_r('stt'):<12} | {fmt_r('llm'):<12} | {fmt_r('tts'):<12} | {v_peak}")
                        # Rich Breakdown
                        stt_ready = m.get('stt',[0,0])[1]
                        stt_text = f"{m.get('stt_text', 'N/A')} ({stt_ready:.2f} → {stt_ready:.2f}s)"
                        llm_text = fmt_with_chunks(m.get('llm_text',''), m.get('llm_chunks',[]))
                        if "(" not in llm_text:
                            llm_end = m.get('llm',[0,0])[1]
                            llm_text = f"{llm_text} ({llm_end:.2f} → {llm_end:.2f}s)"

                        print(f"    \t🎙️ {fmt_r('stt')} | [{s_res.get('stt_model', 'STT')}] | Text: \"{stt_text}\"")     
                        print(f"    \t🧠 {fmt_r('llm')} | [{s_res.get('llm_model', 'LLM')}] | Text: \"{llm_text}\"") 
                        print(f"    \t🔊 {fmt_r('tts')} | [{s_res.get('tts_model', 'TTS')}] | Path: {s_res['result']}")
                    else:
                        stt_end = s_res.get('stt_inf', 0)
                        llm_end = stt_end + s_res.get('llm_tot', 0)
                        tts_end = s_res.get('duration', 0)
                        def fmt_w(t): return f"{t:>4.1f}→{t:<4.1f}s"
                        
                        print(f"  {lid:<30} | {mode:<7} | {s_res['duration']:>7.2f}s | {fmt_w(stt_end):<12} | {fmt_w(llm_end):<12} | {fmt_w(tts_end):<12} | {v_peak}")
                        # Rich Breakdown
                        stt_text = f"{s_res['stt_text']} ({stt_end:.2f} → {stt_end:.2f}s)"
                        llm_text = f"{s_res['llm_text']} ({llm_end:.2f} → {llm_end:.2f}s)"
                        
                        print(f"    \t🎙️ {stt_end:.2f}s | [{s_res['stt_model']}] | Text: \"{stt_text}\"")
                        print(f"    \t🧠 {s_res['llm_tot']:.2f}s | [{s_res['llm_model']}] | Text: \"{llm_text}\"")
                        print(f"    \t🔊 {s_res['tts_inf']:.2f}s | [{s_res['tts_model']}] | Path: {s_res['result']}")
                elif s_res:
                    print(f"  {lid:<30} | {mode:<7} | {RED}{'FAILED':>7}{RESET}  | {'-':<12} | {'-':<12} | {'-':<12} | {v_peak}")

    print("\n" + "="*LINE_LEN)
    print(f"Total S2S Suite Time: {time.perf_counter() - total_start:.2f}s\n")
    
    save_artifact("s2s", suite_results)

if __name__ == "__main__":
    run_s2s_suite()
