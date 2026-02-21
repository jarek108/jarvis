import os
import re
from utils.calibration.common import parse_size_gb, save_calibration

def extract_ollama_metrics(content, default_id=None):
    """Parses Ollama log content for memory metrics and model ID."""
    # Robust Patterns (handle multi-line msg structures)
    re_total = re.compile(r'msg="total memory".*?size="?([^"]+)"?', re.DOTALL)
    re_kv_msg = re.compile(r'msg="kv cache".*?size="?([^"]+)"?', re.DOTALL)
    re_weight_msg = re.compile(r'msg="model weights".*?size="?([^"]+)"?', re.DOTALL)
    re_compute_msg = re.compile(r'msg="compute graph".*?size="?([^"]+)"?', re.DOTALL)
    re_model_msg = re.compile(r'msg="loading model".*?model=([^ ]+)')

    # Low-level llama.cpp patterns
    re_kv_low = re.compile(r'(?:llama_kv_cache:.*?size|KV buffer size)\s*=\s*([\d\.]+)\s*(\w+)i?B')
    re_tokens = re.compile(r'(?:llama_kv_cache: size|KV self size)\s*=\s*.*?\(\s*(\d+)\s*cells')
    re_weight_low = re.compile(r'(?:model size:|model buffer size)\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_compute_low = re.compile(r'compute buffer size\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_model_low = re.compile(r'general.name\s+=\s+(.*)')
    re_model_v3 = re.compile(r'general.name\s+\w+\s+=\s+(.*)')
    
    # Run-folder specific fallback for tokens: KvSize:2048
    re_tokens_fallback = re.compile(r'KvSize:(\d+)')

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
    else:
        m = re_tokens_fallback.search(content)
        if m: cells = int(m.group(1))
    
    # 4. Weights
    m = re_weight_msg.search(content)
    if m: weight_gb = parse_size_gb(m.group(1))
    else:
        weight_matches = re_weight_low.finditer(content)
        for wm in weight_matches:
            weight_gb += parse_size_gb(f"{wm.group(1)} {wm.group(2)}")
    
    # 5. Compute
    m = re_compute_msg.search(content)
    if m: compute_gb = parse_size_gb(m.group(1))
    else:
        compute_matches = re_compute_low.finditer(content)
        for cm in compute_matches:
            compute_gb += parse_size_gb(f"{cm.group(1)} {cm.group(2)}")

    # 6. Model ID
    m = re_model_msg.search(content)
    if m: model_id = m.group(1)
    else:
        m = re_model_low.search(content)
        if m: model_id = m.group(1).strip()
        else:
            m = re_model_v3.search(content)
            if m: model_id = m.group(1).strip()

    if not model_id:
        model_id = default_id

    if not total_gb and (weight_gb > 0 and kv_gb is not None):
        total_gb = weight_gb + kv_gb + compute_gb

    return total_gb, kv_gb, cells, model_id

def calibrate_from_log(model_id, log_path, project_root):
    """Generates a calibration file from an existing Ollama log."""
    if not os.path.exists(log_path):
        return None

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    filename = os.path.basename(log_path)
    default_id = None
    if filename.startswith("svc_llm_OL_"):
        m = re.search(r"svc_llm_OL_(.*?)_\d{8}_\d{6}", filename)
        if m: default_id = m.group(1)
    elif filename.startswith("ol_"):
        default_id = filename[3:].replace(".log", "")
    elif filename.endswith(".log"):
        default_id = filename.replace(".log", "")

    total_gb, kv_gb, cells, extracted_id = extract_ollama_metrics(content, default_id)
    target_id = model_id or extracted_id
    if not target_id: return None

    # Strip flags
    target_id = target_id.split('#')[0]

    if not (total_gb and kv_gb and cells):
        return None
        
    base_vram = total_gb - kv_gb
    gb_per_10k = (kv_gb / cells) * 10000
    return save_calibration(target_id, "ollama", base_vram, gb_per_10k, cells, kv_gb, log_path, project_root)
