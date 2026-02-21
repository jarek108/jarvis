import os
import sys
import argparse

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from utils.calibration.vllm import calibrate_from_log as calibrate_vllm
from utils.calibration.ollama import calibrate_from_log as calibrate_ollama

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Jarvis Model Calibration: Extracts memory physics from logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Auto-detect Model ID:
    python utils/calibrate_model.py model_startup.log --engine vllm
  
  Manual Model ID Override:
    python utils/calibrate_model.py $env:LOCALAPPDATA/Ollama/server.log --engine ollama --model gpt-oss:20b
        """
    )
    parser.add_argument("log_file", type=str, help="Path to the log file to parse")
    parser.add_argument("--model", type=str, help="Optional: Model ID (will try to auto-detect if omitted)")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"], default="vllm", help="Engine type (vllm or ollama)")
    
    args = parser.parse_args()
    
    if args.engine == "ollama":
        calibrate_ollama(args.model, args.log_file, project_root)
    else:
        calibrate_vllm(args.model, args.log_file, project_root)
