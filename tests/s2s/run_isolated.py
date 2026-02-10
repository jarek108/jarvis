import argparse
from utils import run_s2s_isolated_lifecycle

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an isolated S2S pipeline benchmark.")
    parser.add_argument("--loadout", type=str, required=True, help="Loadout ID (e.g. default, eng_turbo)")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output")
    args = parser.parse_args()
    
    run_s2s_isolated_lifecycle(args.loadout, benchmark_mode=args.benchmark_mode)
