import os
import re
import time
import subprocess
import requests
import threading
from .common import parse_size_gb, save_calibration
import utils

def extract_ollama_metrics(content, default_id=None):
    """Parses Ollama log content for memory metrics and model ID."""
    # High-level msg patterns
    re_total = re.compile(r'msg="total memory"\s+size="?([^ "]+)"?')
    re_kv_msg = re.compile(r'msg="kv cache".*?size="?([^ "]+)"?')
    re_weight_msg = re.compile(r'msg="model weights".*?size="?([^ "]+)"?')
    re_compute_msg = re.compile(r'msg="compute graph".*?size="?([^ "]+)"?')
    re_model_msg = re.compile(r'msg="loading model".*?model=([^ ]+)')

    # Low-level llama.cpp patterns
    re_kv_low = re.compile(r'(?:llama_kv_cache:.*?size|KV buffer size)\s*=\s*([\d\.]+)\s*(\w+)i?B')
    re_tokens = re.compile(r'(?:llama_kv_cache: size|KV self size)\s*=\s*.*?\(\s*(\d+)\s*cells')
    re_weight_low = re.compile(r'(?:model size|model buffer size)\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_compute_low = re.compile(r'(?:compute buffer size|output buffer size)\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_model_low = re.compile(r'general.name\s+=\s+(.*)')

    total_gb, kv_gb, cells, model_id = None, None, None, None
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
        # Sum all weight buffers found
        weight_matches = re_weight_low.finditer(content)
        for wm in weight_matches:
            weight_gb += parse_size_gb(f"{wm.group(1)} {wm.group(2)}")
    
    # 5. Compute
    m = re_compute_msg.search(content)
    if m: compute_gb = parse_size_gb(m.group(1))
    else:
        # Sum all compute/output buffers
        compute_matches = re_compute_low.finditer(content)
        for cm in compute_matches:
            compute_gb += parse_size_gb(f"{cm.group(1)} {cm.group(2)}")

    # 6. Model ID
    m = re_model_msg.search(content)
    if m: model_id = m.group(1)
    else:
        m = re_model_low.search(content)
        if m: model_id = m.group(1).strip()

    if not model_id:
        model_id = default_id

    if not total_gb and (weight_gb > 0 and kv_gb is not None):
        total_gb = weight_gb + kv_gb + compute_gb

    return total_gb, kv_gb, cells, model_id

def calibrate_from_log(model_id, log_path, project_root):
    """Generates a calibration file from an existing Ollama log."""
    if not os.path.exists(log_path):
        print(f"❌ Log file not found: {log_path}")
        return

    print(f"📄 Parsing Ollama log: {log_path}")
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # Derive default ID from filename (e.g. "ol_moondream.log" -> "moondream")
    filename = os.path.basename(log_path)
    default_id = None
    if filename.startswith("ol_"):
        default_id = filename[3:].replace(".log", "")
    elif filename.endswith(".log"):
        default_id = filename.replace(".log", "")

    total_gb, kv_gb, cells, extracted_id = extract_ollama_metrics(content, default_id)
    
    target_id = model_id or extracted_id
    if not target_id:
        print("❌ Error: Could not extract Model ID from log. Please provide it manually.")
        return

    if not (total_gb and kv_gb and cells):
        print(f"❌ Failed to extract metrics from {log_path}")
        if not total_gb: print(f"  - Missing: Total/Weight metrics (Found Weight: {weight_gb if 'weight_gb' in locals() else 'None'} GB)")
        if not kv_gb: print("  - Missing: KV Cache metric")
        if not cells: print("  - Missing: Token cells metric")
        return None
        
    base_vram = total_gb - kv_gb
    gb_per_10k = (kv_gb / cells) * 10000
    
    return save_calibration(target_id, "ollama", base_vram, gb_per_10k, cells, kv_gb, log_path, project_root)
