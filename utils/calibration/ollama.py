import re
import os
from .common import parse_size_gb, save_calibration

def extract_ollama_metrics(content):
    """Parses Ollama log content for memory metrics."""
    # High-level msg patterns
    re_total = re.compile(r'msg="total memory" size="?([^ "]+)"?')
    re_kv_msg = re.compile(r'msg="kv cache" device=CUDA0 size="?([^ "]+)"?')
    re_weight_msg = re.compile(r'msg="model weights" device=CUDA0 size="?([^ "]+)"?')
    re_compute_msg = re.compile(r'msg="compute graph" device=CUDA0 size="?([^ "]+)"?')

    # Low-level llama.cpp patterns
    re_kv_low = re.compile(r'(?:llama_kv_cache:.*?size|KV buffer size)\s*=\s*([\d\.]+)\s*(\w+)i?B')
    re_tokens = re.compile(r'(?:llama_kv_cache: size|KV self size)\s*=\s*.*?\(\s*(\d+)\s*cells')
    re_weight_low = re.compile(r'(?:model size:|model buffer size)\s*=\s*([\d\.]+)\s*(\w+)i?B')
    re_compute_low = re.compile(r'compute buffer size\s*=\s*([\d\.]+)\s*(\w+)i?B')

    total_gb, kv_gb, cells = None, None, None
    weight_gb, compute_gb = 0.0, 0.0

    # 1. Total (if available)
    m = re_total.search(content)
    if m: total_gb = parse_size_gb(m.group(1))
    
    # 2. KV Cache
    m = re_kv_msg.search(content)
    if m: kv_gb = parse_size_gb(m.group(1))
    else:
        m = re_kv_low.search(content)
        if m: kv_gb = parse_size_gb(f"{m.group(1)} {m.group(2)}")
    
    # 3. Tokens
    m = re_tokens.search(content)
    if m: cells = int(m.group(1))
    
    # 4. Weights
    m = re_weight_msg.search(content)
    if m: weight_gb = parse_size_gb(m.group(1))
    else:
        m = re_weight_low.search(content)
        if m: weight_gb = parse_size_gb(f"{m.group(1)} {m.group(2)}")
    
    # 5. Compute
    m = re_compute_msg.search(content)
    if m: compute_gb = parse_size_gb(m.group(1))
    else:
        compute_matches = re_compute_low.finditer(content)
        for cm in compute_matches:
            compute_gb += parse_size_gb(f"{cm.group(1)} {cm.group(2)}")

    if not total_gb and (weight_gb and kv_gb):
        total_gb = weight_gb + kv_gb + compute_gb

    return total_gb, kv_gb, cells

def calibrate_from_log(model_id, log_path, project_root):
    """Generates a calibration file from an existing Ollama log."""
    if not os.path.exists(log_path):
        print(f"❌ Log file not found: {log_path}")
        return

    print(f"📄 Parsing Ollama log: {log_path}")
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    total_gb, kv_gb, cells = extract_ollama_metrics(content)
    
    if not (total_gb and kv_gb and cells):
        print(f"❌ Failed to extract metrics from {log_path}")
        if not total_gb: print("  - Missing: Total/Weight metrics")
        if not kv_gb: print("  - Missing: KV Cache metric")
        if not cells: print("  - Missing: Token cells metric")
        return None
        
    base_vram = total_gb - kv_gb
    gb_per_10k = (kv_gb / cells) * 10000
    
    return save_calibration(model_id, "ollama", base_vram, gb_per_10k, cells, kv_gb, log_path, project_root)
