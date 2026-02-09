from utils import run_stt_isolated_lifecycle

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-mode", action="store_true")
    args = parser.parse_args()
    run_stt_isolated_lifecycle("faster-whisper-large", benchmark_mode=args.benchmark_mode)
