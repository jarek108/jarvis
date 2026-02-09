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

def run_tts_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    chatterbox_dir = os.path.join(base_dir, "chatterbox")
    # UPDATED SCRIPT MAPPING
    variants = ["eng", "multilingual", "turbo"]
    
    suite_results = []
    total_start = time.perf_counter()

    python_exe = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "jarvis-venv", "Scripts", "python.exe")

    LINE_LEN = 140

    for var in variants:
        variant_id = f"chatterbox-{var}"
        print(f"\n>>> Running TTS Suite: {variant_id}")
        isolated_script = os.path.join(chatterbox_dir, f"isolated_{var}.py")
        if not os.path.exists(isolated_script): 
            print(f"FAILED: {isolated_script} not found.")
            continue

        try:
            # Capture output so we can see the individual table
            process = subprocess.run([python_exe, isolated_script], capture_output=True, text=True)
            
            # Re-print the captured table from the individual test
            print(process.stdout)
            if process.stderr: print(process.stderr, file=sys.stderr)

            # Check for success
            success = process.returncode == 0
            suite_results.append({
                "suite": variant_id,
                "status": "PASSED" if success else "FAILED",
                "duration": time.perf_counter() - total_start
            })
        except Exception as e:
            suite_results.append({"suite": variant_id, "status": "FAILED", "duration": 0})

    # --- MINIMAL FINAL SUMMARY ---
    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'TTS SUITE COMPLETION SUMMARY':^140}{RESET}")
    print("="*LINE_LEN)
    for res in suite_results:
        print(f"  {format_status(res['status'])} | {res['suite']:<25} | Completed")
    print("="*LINE_LEN)
    print(f"Total TTS Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_tts_suite()
