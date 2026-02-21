import os
import sys
import argparse
import re

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# Use absolute imports based on project root
from utils.calibration.vllm import calibrate_from_log as calibrate_vllm
from utils.calibration.ollama import calibrate_from_log as calibrate_ollama

def detect_engine(content):
    """Identifies the inference engine based on log signatures."""
    if "source=server.go" in content or 'msg="' in content or "[GIN]" in content or "llama_kv_cache:" in content or "clip_model_loader:" in content:
        return "ollama"
    if "(APIServer" in content or "vLLM API server" in content or "Model loading took" in content:
        return "vllm"
    return None

def process_file(log_path, model_override=None, engine_override=None):
    """Calibrates a single log file with error handling. Returns status code."""
    try:
        if not os.path.isfile(log_path): return 1
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            sample = f.read(50000)
        engine = engine_override or detect_engine(sample)
        if not engine: return 1
        result = calibrate_ollama(model_override, log_path, project_root) if engine == "ollama" else calibrate_vllm(model_override, log_path, project_root)
        return 0 if result else 2
    except Exception as e:
        print(f"💥 Error processing {os.path.basename(log_path)}: {e}")
        return 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Jarvis Model Calibration: Fully automated memory physics from logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Batch Calibrate Folder:
    python utils/calibration/calibrate.py model_calibrations/source_logs/
  Single Log:
    python utils/calibration/calibrate.py my_log.log
        """
    )
    parser.add_argument("path", type=str, help="Path to a log file or a directory of logs")
    parser.add_argument("--model", type=str, help="Optional: Model ID override")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"], help="Optional: Engine type override")
    
    args = parser.parse_args()
    if not os.path.exists(args.path):
        print(f"❌ Path not found: {args.path}"); sys.exit(1)

    if os.path.isdir(args.path):
        print(f"📂 Batch processing directory: {args.path}")
        files = [os.path.join(args.path, f) for f in os.listdir(args.path) if os.path.isfile(os.path.join(args.path, f))]
        stats = {0: 0, 1: 0, 2: 0}
        for f_path in files:
            if os.path.basename(f_path).startswith('.') or f_path.endswith(('.yaml', '.xlsx', '.json', '.wav')):
                stats[1] += 1; continue
            stats[process_file(f_path, engine_override=args.engine)] += 1
        print(f"\n✨ Batch complete. Success: {stats[0]}, Skipped: {stats[1]}, Failed: {stats[2]}")
    else:
        process_file(args.path, model_override=args.model, engine_override=args.engine)
