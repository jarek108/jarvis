import os
import sys
import time
import subprocess

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils import CYAN, BOLD, RESET, LINE_LEN

def run_master_suite():
    total_start = time.perf_counter()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable

    suites = [
        {"name": "LLM Comparison", "path": "llm/run_extensive_comparison.py"},
        {"name": "TTS Extensive", "path": "tts/run_extensive_comparison.py"},
        {"name": "STT Extensive", "path": "stt/run_extensive_comparison.py"},
        {"name": "S2S Extensive", "path": "s2s/run_extensive_comparison.py"}
    ]

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'STARTING GLOBAL JARVIS EXTENSIVE COMPARISON':^120}{RESET}")
    print("#"*LINE_LEN)

    for suite in suites:
        script_path = os.path.join(base_dir, suite['path'])
        # Add tests root to PYTHONPATH so isolated scripts can find utils.py
        env = os.environ.copy()
        env["PYTHONPATH"] = base_dir + os.pathsep + env.get("PYTHONPATH", "")

        try:
            subprocess.run([python_exe, script_path], cwd=os.path.dirname(script_path), env=env)
        except Exception as e:
            print(f"Error running {suite['name']}: {e}")

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'JARVIS EXTENSIVE COMPARISON COMPLETE':^120}{RESET}")
    print(f"{BOLD}{'Total Execution Time: ' + str(round(time.perf_counter() - total_start, 2)) + 's':^120}{RESET}")
    print("#"*LINE_LEN + "\n")

if __name__ == "__main__":
    # Add root of tests/ to sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    run_master_suite()