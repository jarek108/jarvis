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
    if m: model_id = m.group(1).split('#')[0] # Strip flags
    
    return base_vram, cache_gb, tokens, model_id

def calibrate_from_log(model_id, log_path, project_root):
    """Generates a calibration file from an existing vLLM log."""
    if not os.path.exists(log_path):
        return None

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    base_vram, cache_gb, tokens, extracted_id = extract_vllm_metrics(content)
    
    # Filename fallback for vLLM
    filename = os.path.basename(log_path)
    if not extracted_id and filename.startswith("svc_llm_VL_"):
        m = re.search(r"svc_llm_VL_(.*?)_\d{8}_\d{6}", filename)
        if m: extracted_id = m.group(1)

    target_id = model_id or extracted_id
    if not target_id: return None

    # Sanitize target_id (remove flags)
    target_id = target_id.split('#')[0]

    if not (base_vram and cache_gb and tokens):
        return None
        
    gb_per_10k = (cache_gb / tokens) * 10000
    return save_calibration(target_id, "vllm", base_vram, gb_per_10k, tokens, cache_gb, log_path, project_root)
