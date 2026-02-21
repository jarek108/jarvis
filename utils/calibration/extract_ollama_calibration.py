import re
import yaml
import argparse
import os
import sys

def parse_size(size_str):
    """Converts '18.1 GiB' or '876.0 MiB' to float GB."""
    m = re.match(r""?([\d\.]+) (\w+)i?B"?", size_str)
    if not m: return 0.0
    val, unit = float(m.group(1)), m.group(2).upper()
    if unit == 'M': return val / 1024.0
    if unit == 'G': return val
    return val

def extract_from_log(log_path):
    if not os.path.exists(log_path):
        print(f"❌ File not found: {log_path}")
        return

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 1. Extract Weights & Total (High level Ollama logs)
    # msg="model weights" device=CUDA0 size="18.1 GiB"
    weights_match = re.search(r'msg="model weights" device=CUDA0 size=([^ ]+)', content)
    # msg="total memory" size="22.0 GiB"
    total_match = re.search(r'msg="total memory" size=([^ 
]+)', content)
    # msg="kv cache" device=CUDA0 size="3.0 GiB"
    kv_match = re.search(r'msg="kv cache" device=CUDA0 size=([^ ]+)', content)
    
    # 2. Extract Token count (Low level llama.cpp logs)
    # llama_kv_cache: size =  384.00 MiB ( 32768 cells, ...
    tokens_match = re.search(r'llama_kv_cache: size = .*?\( +(\d+) cells', content)

    if not (total_match and kv_match and tokens_match):
        print("❌ Could not find all required metrics in log.")
        if not total_match: print("  - Missing: total memory")
        if not kv_match: print("  - Missing: kv cache size")
        if not tokens_match: print("  - Missing: token cells")
        return

    total_gb = parse_size(total_match.group(1))
    kv_gb = parse_size(kv_match.group(1))
    tokens = int(tokens_match.group(1))

    base_vram = total_gb - kv_gb
    gb_per_10k = (kv_gb / tokens) * 10000

    # Try to find model ID
    # model D:\...\blobs\...
    id_match = re.search(r'msg="loading model".*?model=([^ ]+)', content)
    model_id = id_match.group(1) if id_match else "unknown_model"

    result = {
        "id": model_id,
        "engine": "ollama",
        "constants": {
            "base_vram_gb": round(base_vram, 4),
            "kv_cache_gb_per_10k": round(gb_per_10k, 6),
        },
        "metadata": {
            "extracted_from": os.path.basename(log_path),
            "source_tokens": tokens,
            "source_kv_gb": round(kv_gb, 4),
            "source_total_gb": round(total_gb, 4)
        }
    }

    print(yaml.dump(result, sort_keys=False))
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Ollama VRAM physics from logs")
    parser.add_argument("log_file", help="Path to Ollama session log")
    args = parser.parse_args()
    extract_from_log(args.log_file)
