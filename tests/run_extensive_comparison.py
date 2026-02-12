import os
import sys
import subprocess
import argparse

def run_extensive():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable
    runner_path = os.path.join(base_dir, "runner.py")
    
    parser = argparse.ArgumentParser(description="Jarvis Global Extensive Comparison")
    parser.add_argument("--local", action="store_true", help="Skip cloud upload")
    args = parser.parse_args()

    # The master suite is now just a specific call to the unified runner
    # We use --purge to ensure bit-perfect benchmarks across model swaps
    cmd = [python_exe, runner_path, "--purge", "--benchmark-mode"]
    if args.local:
        cmd.append("--local")
        
    subprocess.run(cmd)

if __name__ == "__main__":
    run_extensive()
