import os
import sys
import argparse
import re

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from utils.calibration.vllm import calibrate_from_log as calibrate_vllm
from utils.calibration.ollama import calibrate_from_log as calibrate_ollama

def detect_engine(content):
    """Identifies the inference engine based on log signatures."""
    # vLLM Signatures
    if "(APIServer" in content or "vLLM API server" in content or "Model loading took" in content:
        return "vllm"
    
    # Ollama Signatures
    if "source=server.go" in content or 'msg="' in content or "[GIN]" in content or "llama_kv_cache:" in content:
        return "ollama"
    
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Jarvis Model Calibration: Fully automated memory physics from logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Fully Automated (Auto-Engine + Auto-Model):
    python utils/calibrate_model.py my_log.log
  
  Manual Override:
    python utils/calibrate_model.py server.log --engine ollama --model gpt-oss:20b
        """
    )
    parser.add_argument("log_file", type=str, help="Path to the log file to parse")
    parser.add_argument("--model", type=str, help="Optional: Model ID (will auto-detect if omitted)")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"], help="Optional: Engine type (will auto-detect if omitted)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.log_file):
        print(f"❌ Log file not found: {args.log_file}")
        sys.exit(1)

    with open(args.log_file, "r", encoding="utf-8", errors="ignore") as f:
        # Read first 10k chars for detection
        sample = f.read(10000)
    
    engine = args.engine or detect_engine(sample)
    
    if not engine:
        print("❌ Error: Could not auto-detect engine type. Please specify with --engine.")
        sys.exit(1)

    print(f"🤖 Detected Engine: {engine.upper()}")
    
    if engine == "ollama":
        calibrate_ollama(args.model, args.log_file, project_root)
    else:
        calibrate_vllm(args.model, args.log_file, project_root)
