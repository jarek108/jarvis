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

def run_stt_suite():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    whisper_dir = os.path.join(base_dir, "whisper")
    # UPDATED NAMES
    sizes = ["faster-whisper-tiny", "faster-whisper-base", "faster-whisper-small", "faster-whisper-medium", "faster-whisper-large"]
    
    suite_results = []
    total_start = time.perf_counter()

    python_exe = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "jarvis-venv", "Scripts", "python.exe")
    
    env = os.environ.copy()
    tests_root = os.path.dirname(base_dir)
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = tests_root + os.pathsep + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = tests_root

    LINE_LEN = 140

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'WHISPER MULTI-SIZE BENCHMARK RUN':^140}{RESET}")
    print("#"*LINE_LEN)

    for size_id in sizes:
        print(f"\n>>> Loading Model: {size_id.upper()}")
        short_name = size_id.replace("faster-whisper-", "")
        isolated_script = os.path.join(whisper_dir, f"isolated_{short_name}.py")
        
        try:
            # Capture output
            process = subprocess.run([python_exe, isolated_script], env=env, capture_output=False, text=True)
            
            suite_results.append({
                "size": size_id,
                "status": "PASSED" if process.returncode == 0 else "FAILED"
            })
        except Exception as e:
            suite_results.append({"size": size_id, "status": "FAILED"})

    print("\n" + "="*LINE_LEN)
    print(f"{BOLD}{'STT MULTI-SIZE BENCHMARK SUMMARY':^140}{RESET}")
    print("="*LINE_LEN)
    for res in suite_results:
        print(f"  {format_status(res['status'])} | {res['size']:<25} | Completed")
    print("="*LINE_LEN)
    print(f"Total STT Suite Time: {time.perf_counter() - total_start:.2f}s\n")

if __name__ == "__main__":
    run_stt_suite()
