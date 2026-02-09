import os
import sys
import time
import subprocess
import json

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import format_status, CYAN, BOLD, RESET, LINE_LEN

def run_tts_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    chatterbox_dir = os.path.join(base_dir, "chatterbox")
    variants = ["eng", "multilingual", "turbo"]
    
    suite_results = []
    total_start = time.perf_counter()

    python_exe = os.path.join(os.path.dirname(os.path.dirname(base_dir)), "jarvis-venv", "Scripts", "python.exe")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(base_dir) + os.pathsep + env.get("PYTHONPATH", "")

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'CHATTERBOX MULTI-VARIANT BENCHMARK RUN':^120}{RESET}")
    print("#"*LINE_LEN)

    for var in variants:
        variant_id = f"chatterbox-{var}"
        print(f"\n>>> Running TTS Suite: {variant_id}")
        isolated_script = os.path.join(chatterbox_dir, f"isolated_{var}.py")
        
        try:
            # Capture output to filter machine lines
            process = subprocess.run([python_exe, isolated_script], env=env, capture_output=True, text=True, encoding='utf-8')
            
            for line in process.stdout.splitlines():
                if not (line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ")):
                    print(line)

            success = process.returncode == 0
            suite_results.append({
                "suite": variant_id,
                "status": "PASSED" if success else "FAILED"
            })
        except Exception as e:
            print(f"Error running {variant_id}: {e}")
            suite_results.append({"suite": variant_id, "status": "FAILED"})

    # --- MINIMAL FINAL SUMMARY ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'TTS SUITE COMPLETION SUMMARY':^120}{RESET}")
    print("="*LINE_LEN)
    for res in suite_results:
        print(f"  {format_status(res['status'])} | {res['suite']:<25} | Completed")
    print("="*LINE_LEN)
    print(f"Total TTS Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_tts_suite()