import os
import sys
import time
import subprocess

# Allow importing utils from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils import CYAN, BOLD, RESET, LINE_LEN

import argparse

from utils import CYAN, BOLD, RESET, LINE_LEN, trigger_report_generation



def run_master_suite(upload=True):

    total_start = time.perf_counter()

    base_dir = os.path.dirname(os.path.abspath(__file__))

    python_exe = sys.executable



    suites = [

        {"name": "LLM Comparison", "path": "llm/run_extensive_comparison.py"},

        {"name": "VLM Comparison", "path": "vlm/run_extensive_comparison.py"},

        {"name": "STT Extensive", "path": "stt/run_extensive_comparison.py"},

        {"name": "TTS Extensive", "path": "tts/run_extensive_comparison.py"},

        {"name": "S2S Extensive", "path": "s2s/run_extensive_comparison.py"}

    ]



    print("#"*LINE_LEN)

    print(f"{BOLD}{CYAN}{'STARTING GLOBAL JARVIS EXTENSIVE COMPARISON':^120}{RESET}")

    print("#"*LINE_LEN)



    for suite in suites:

        script_path = os.path.join(base_dir, suite['path'])

        env = os.environ.copy()

        env["PYTHONPATH"] = base_dir + os.pathsep + env.get("PYTHONPATH", "")



        try:

            # Pass --local to all sub-suites to prevent redundant individual uploads

            cmd = [python_exe, script_path, "--local"]

            subprocess.run(cmd, cwd=os.path.dirname(script_path), env=env)

        except Exception as e:

            print(f"Error running {suite['name']}: {e}")



    print("\n" + "#"*LINE_LEN)

    print(f"{BOLD}{'JARVIS EXTENSIVE COMPARISON COMPLETE':^120}{RESET}")

    print(f"{BOLD}{'Total Execution Time: ' + str(round(time.perf_counter() - total_start, 2)) + 's':^120}{RESET}")

    print("#"*LINE_LEN + "\n")

    

    # Trigger the FINAL consolidated report and upload

    trigger_report_generation(upload=upload)



if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Jarvis Master Extensive Comparison")

    parser.add_argument("--local", action="store_true", help="Skip cloud upload")

    args = parser.parse_args()

    

    # Add root of tests/ to sys.path

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    run_master_suite(upload=not args.local)
