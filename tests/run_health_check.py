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
    python_exe = os.path.join(os.path.dirname(base_dir), "jarvis-venv", "Scripts", "python.exe")

    suites = [
        {"name": "STT (Base)", "path": "stt/test.py", "args": ["--loadout", "base-qwen30-multi"]},
        {"name": "TTS (Turbo)", "path": "tts/test.py", "args": ["--loadout", "tiny-gpt20-turbo"]},
        {"name": "sts (Default)", "path": "sts/test.py", "args": ["--loadout", "base-qwen30-multi"]}
    ]

    print("#"*LINE_LEN)
    print(f"{BOLD}{CYAN}{'STARTING JARVIS HEALTH CHECK (Representative Subset)':^120}{RESET}")
    print("#"*LINE_LEN)

    for suite in suites:
        script_path = os.path.join(base_dir, suite['path'])
        # Add tests root to PYTHONPATH so isolated scripts can find utils.py
        env = os.environ.copy()
        env["PYTHONPATH"] = base_dir + os.pathsep + env.get("PYTHONPATH", "")
        
        try:
            # Explicitly run in its own directory
            cmd = [python_exe, script_path] + suite.get("args", [])
            subprocess.run(cmd, cwd=os.path.dirname(script_path), env=env)
        except Exception as e:
            print(f"Error running {suite['name']} suite: {e}")

    print("\n" + "#"*LINE_LEN)
    print(f"{BOLD}{'JARVIS HEALTH CHECK COMPLETE':^120}{RESET}")
    print(f"{BOLD}{'Total Execution Time: ' + str(round(time.perf_counter() - total_start, 2)) + 's':^120}{RESET}")
    print("#"*LINE_LEN + "\n")

if __name__ == "__main__":
    # Add root of tests/ to sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    run_master_suite()
