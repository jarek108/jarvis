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
        {"name": "STT (Base)", "path": "stt/whisper/isolated_base.py"},
        {"name": "TTS (Eng)", "path": "tts/chatterbox/isolated_eng.py"},
        {"name": "S2S (Default)", "path": "s2s/isolated_default.py"}
    ]

    LINE_LEN = 140

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'STARTING NORMAL JARVIS TEST SUITE (Representative Subset)':^140}{RESET}")
    print("#"*LINE_LEN)

    for suite in suites:
        print(f"\n\n{BOLD}{'#'*60} Suite: {suite['name']} {'#'*60}{RESET}")
        script_path = os.path.join(base_dir, suite['path'])
        try:
            # Explicitly run in its own directory
            subprocess.run([python_exe, script_path], cwd=os.path.dirname(script_path))
        except Exception as e:
            print(f"Error running {suite['name']} suite: {e}")

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'JARVIS NORMAL HEALTH REPORT COMPLETE':^140}{RESET}")
    print(f"{BOLD}{'Total Execution Time: ' + str(round(time.perf_counter() - total_start, 2)) + 's':^140}{RESET}")
    print("#"*LINE_LEN + "\n")

if __name__ == "__main__":
    # Add root of tests/ to sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    run_master_suite()