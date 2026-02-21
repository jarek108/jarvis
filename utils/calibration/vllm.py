import os
import re
from .common import save_calibration

def extract_vllm_metrics(content):
    """Parses vLLM log content for memory metrics and model ID."""
    re_base = re.compile(r"Model loading took ([\d\.]+) GiB memory")
    re_cache_gb = re.compile(r"Available KV cache memory: ([\d\.]+) GiB")
    re_tokens = re.compile(r"GPU KV cache size: ([\d,]+) tokens")
    re_model = re.compile(r"model\s+([\w\-/.-]+)")

    base_vram, cache_gb, tokens, model_id = None, None, None, None
    
    m = re_base.search(content)
    if m: base_vram = float(m.group(1))
    
    m = re_cache_gb.search(content)
    if m: cache_gb = float(m.group(1))
    
    m = re_tokens.search(content)
    if m: tokens = int(m.group(1).replace(",", ""))

    m = re_model.search(content)
    if m: model_id = m.group(1)
    
    return base_vram, cache_gb, tokens, model_id

def calibrate_from_log(model_id, log_path, project_root):
    """Generates a calibration file from an existing vLLM log."""
    if not os.path.exists(log_path):
        print(f"❌ Log file not found: {log_path}")
        return

    print(f"📄 Parsing vLLM log: {log_path}")
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    base_vram, cache_gb, tokens, extracted_id = extract_vllm_metrics(content)
    
    target_id = model_id or extracted_id
    if not target_id:
        print("❌ Error: Could not extract Model ID from log. Please provide it manually.")
        return

    if not (base_vram and cache_gb and tokens):
        print(f"❌ Failed to extract metrics from {log_path}")
        if not base_vram: print("  - Missing: Base VRAM metric")
        if not cache_gb: print("  - Missing: Cache memory metric")
        if not tokens: print("  - Missing: KV Tokens metric")
        return None
        
    gb_per_10k = (cache_gb / tokens) * 10000
    return save_calibration(target_id, "vllm", base_vram, gb_per_10k, tokens, cache_gb, log_path, project_root)
