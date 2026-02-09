from utils import run_s2s_isolated_lifecycle

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-mode", action="store_true")
    args = parser.parse_args()
    run_s2s_isolated_lifecycle("turbo_ultra", benchmark_mode=args.benchmark_mode)