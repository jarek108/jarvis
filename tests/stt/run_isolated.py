import argparse
from utils import run_stt_isolated_lifecycle

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an isolated STT performance benchmark.")
    parser.add_argument("--model", type=str, required=True, help="STT model ID from config.yaml")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()
    
    run_stt_isolated_lifecycle(args.model, benchmark_mode=args.benchmark_mode)
