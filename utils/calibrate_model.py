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
  vLLM:
    python utils/calibrate_model.py Qwen/Qwen2-VL-2B-Instruct vllm_startup.log --engine vllm
  
  Ollama:
    python utils/calibrate_model.py gpt-oss:20b $env:LOCALAPPDATA/Ollama/server.log --engine ollama
        """
    )
    parser.add_argument("model", type=str, help="Model ID (e.g., qwen2.5:0.5b or VL_Qwen/Qwen2-VL-2B-Instruct)")
    parser.add_argument("log_file", type=str, help="Path to the log file to parse")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"], default="vllm", help="Engine type (vllm or ollama)")
    
    args = parser.parse_args()
    
    if args.engine == "ollama":
        calibrate_ollama(args.model, args.log_file, project_root)
    else:
        calibrate_vllm(args.model, args.log_file, project_root)
