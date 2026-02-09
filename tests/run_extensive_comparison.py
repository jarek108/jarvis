import os
import sys
import time
import subprocess

# ANSI Colors
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def run_master_suite():
    total_start = time.perf_counter()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = os.path.join(os.path.dirname(base_dir), "jarvis-venv", "Scripts", "python.exe")

    suites = [
        {"name": "TTS Extensive", "path": "tts/run_extensive_comparison.py"},
        {"name": "STT Extensive", "path": "stt/run_extensive_comparison.py"},
        {"name": "S2S Extensive", "path": "s2s/run_extensive_comparison.py"}
    ]

    for suite in suites:
        script_path = os.path.join(base_dir, suite['path'])
        try:
            subprocess.run([python_exe, script_path], cwd=os.path.dirname(script_path))
        except Exception as e:
            print(f"Error running {suite['name']}: {e}")

    print(f"\n{BOLD}EXTENSIVE SUITE COMPLETE | Total Time: {time.perf_counter() - total_start:.2f}s{RESET}\n")

if __name__ == "__main__":
    # Add root of tests/ to sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    run_master_suite()