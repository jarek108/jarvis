import argparse
from utils import run_llm_isolated_lifecycle
from tests import run_test

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an isolated LLM performance audit.")
    parser.add_argument("--model", type=str, required=True, help="Ollama model name")
    args = parser.parse_args()
    
    run_llm_isolated_lifecycle(args.model, lambda: run_test(args.model))
